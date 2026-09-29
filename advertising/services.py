from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import AdCampaign, AdCreative, AdImpression, AdPurchase

MAX_PURCHASE_AMOUNT_MINOR = 10_000_000
MAX_IDEMPOTENCY_KEY_LENGTH = 64


class CampaignNotEligible(ValidationError):
    pass


class InsufficientBudget(ValidationError):
    pass


class IdempotencyConflict(ValidationError):
    pass


def require_campaign_access(actor, campaign):
    if (
        not actor
        or not getattr(actor, 'is_authenticated', False)
        or not getattr(actor, 'is_active', False)
    ):
        raise PermissionDenied('Authentication is required to manage campaigns.')

    user_model = get_user_model()
    is_owner = (
        campaign.owner_id == actor.pk
        and actor.user_type == user_model.UserType.AD_MANAGER
    )
    is_authorized_staff = (
        actor.is_staff and actor.has_perm('advertising.change_adcampaign')
    )
    if is_owner or is_authorized_staff:
        return
    raise PermissionDenied('You may only manage your own campaigns.')


def _validate_purchase_amount(amount_minor):
    if (
        isinstance(amount_minor, bool)
        or not isinstance(amount_minor, int)
        or amount_minor < 1
        or amount_minor > MAX_PURCHASE_AMOUNT_MINOR
    ):
        raise ValidationError(
            f'Amount must be a whole number of minor units from 1 to '
            f'{MAX_PURCHASE_AMOUNT_MINOR}.'
        )


@transaction.atomic
def purchase_campaign(*, actor, campaign_id, amount_minor):
    campaign = (
        AdCampaign.objects.select_for_update()
        .select_related('owner')
        .get(pk=campaign_id)
    )
    require_campaign_access(actor, campaign)
    _validate_purchase_amount(amount_minor)

    now = timezone.now()
    if campaign.status == AdCampaign.Status.ENDED or campaign.ends_at <= now:
        raise CampaignNotEligible('Ended campaigns cannot be funded.')

    purchase = AdPurchase.objects.create(
        campaign=campaign,
        purchaser=actor,
        amount_minor=amount_minor,
        payment_method=AdPurchase.PaymentMethod.SIMULATED,
        status=AdPurchase.Status.COMPLETED,
    )
    updated = AdCampaign.objects.filter(pk=campaign.pk).update(
        funded_total_minor=F('funded_total_minor') + amount_minor,
        status=(
            AdCampaign.Status.ACTIVE
            if campaign.status == AdCampaign.Status.DRAFT
            else campaign.status
        ),
        updated_at=now,
    )
    if not updated:
        raise CampaignNotEligible('Campaign is no longer available for funding.')
    return purchase


ALLOWED_STATUS_TRANSITIONS = {
    AdCampaign.Status.DRAFT: {
        AdCampaign.Status.ACTIVE,
        AdCampaign.Status.PAUSED,
        AdCampaign.Status.ENDED,
    },
    AdCampaign.Status.ACTIVE: {
        AdCampaign.Status.PAUSED,
        AdCampaign.Status.ENDED,
    },
    AdCampaign.Status.PAUSED: {
        AdCampaign.Status.ACTIVE,
        AdCampaign.Status.ENDED,
    },
    AdCampaign.Status.ENDED: set(),
}


@transaction.atomic
def transition_campaign_status(*, actor, campaign_id, status):
    campaign = (
        AdCampaign.objects.select_for_update()
        .select_related('owner')
        .get(pk=campaign_id)
    )
    require_campaign_access(actor, campaign)

    if status not in AdCampaign.Status.values:
        raise ValidationError({'status': 'Unknown campaign status.'})
    if status == campaign.status:
        return campaign
    if status not in ALLOWED_STATUS_TRANSITIONS[campaign.status]:
        raise ValidationError({'status': 'This campaign status transition is not allowed.'})
    if status == AdCampaign.Status.ACTIVE:
        if (
            campaign.remaining_minor < campaign.impression_cost_minor
            or campaign.ends_at <= timezone.now()
        ):
            raise CampaignNotEligible('Only funded campaigns that have not ended can run.')

    campaign.status = status
    campaign.save(update_fields=('status', 'updated_at'))
    return campaign


def _existing_impression(*, viewer, creative_id, idempotency_key):
    impression = AdImpression.objects.filter(
        viewer=viewer,
        idempotency_key=idempotency_key,
    ).first()
    if impression and impression.creative_id != creative_id:
        raise IdempotencyConflict('This idempotency key was already used for another ad.')
    return impression


def _validate_idempotency_key(idempotency_key):
    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key.strip()
        or len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH
    ):
        raise ValidationError('Provide an idempotency key of 1 to 64 characters.')


def charge_impression(*, viewer, creative_id, idempotency_key):
    if (
        not viewer
        or not getattr(viewer, 'is_authenticated', False)
        or not getattr(viewer, 'is_active', False)
    ):
        raise PermissionDenied('An authenticated viewer is required.')
    _validate_idempotency_key(idempotency_key)

    existing = _existing_impression(
        viewer=viewer,
        creative_id=creative_id,
        idempotency_key=idempotency_key,
    )
    if existing:
        return existing

    try:
        with transaction.atomic():
            creative = AdCreative.objects.get(pk=creative_id)
            campaign = AdCampaign.objects.select_for_update().get(
                pk=creative.campaign_id
            )
            creative = AdCreative.objects.select_for_update().get(
                pk=creative.pk,
                campaign_id=campaign.pk,
            )
            existing = _existing_impression(
                viewer=viewer,
                creative_id=creative.pk,
                idempotency_key=idempotency_key,
            )
            if existing:
                return existing

            now = timezone.now()
            if (
                campaign.status != AdCampaign.Status.ACTIVE
                or not campaign.starts_at <= now < campaign.ends_at
                or not creative.is_active
                or not creative.is_approved
            ):
                raise CampaignNotEligible('This ad is not eligible for delivery.')

            charge = campaign.impression_cost_minor
            # SQLite ignores row locks; use PostgreSQL for production concurrent billing.
            updated = AdCampaign.objects.filter(
                pk=campaign.pk,
                status=AdCampaign.Status.ACTIVE,
                starts_at__lte=now,
                ends_at__gt=now,
                funded_total_minor__gte=F('spent_total_minor') + charge,
            ).update(
                spent_total_minor=F('spent_total_minor') + charge,
                updated_at=now,
            )
            if not updated:
                campaign.refresh_from_db()
                if (
                    campaign.status != AdCampaign.Status.ACTIVE
                    or not campaign.starts_at <= now < campaign.ends_at
                ):
                    raise CampaignNotEligible('This campaign is not active.')
                raise InsufficientBudget('Campaign has insufficient remaining budget.')

            return AdImpression.objects.create(
                campaign=campaign,
                creative=creative,
                viewer=viewer,
                idempotency_key=idempotency_key,
                charged_amount_minor=charge,
            )
    except IntegrityError:
        existing = _existing_impression(
            viewer=viewer,
            creative_id=creative_id,
            idempotency_key=idempotency_key,
        )
        if existing:
            return existing
        raise
