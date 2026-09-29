from datetime import timedelta

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from .models import AdCampaign, AdCreative, AdImpression, AdPurchase
from .services import (
    CampaignNotEligible,
    IdempotencyConflict,
    InsufficientBudget,
    charge_impression,
    purchase_campaign,
    transition_campaign_status,
)


class AdvertisingServiceTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username='ad-manager',
            user_type=User.UserType.AD_MANAGER,
        )
        self.other_manager = User.objects.create_user(
            username='other-manager',
            user_type=User.UserType.AD_MANAGER,
        )
        self.member = User.objects.create_user(username='member')
        self.staff = User.objects.create_user(username='staff', is_staff=True)
        now = timezone.now()
        self.campaign = AdCampaign.objects.create(
            owner=self.manager,
            name='Spring campaign',
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=30),
            impression_cost_minor=100,
        )
        self.creative = AdCreative.objects.create(
            campaign=self.campaign,
            headline='Try this product',
            body='A sponsored demo ad.',
            destination_url='https://example.test/product',
            is_active=True,
            is_approved=True,
        )

    def test_owner_can_fund_campaign_and_balance_updates_with_ledger(self):
        purchase = purchase_campaign(
            actor=self.manager,
            campaign_id=self.campaign.pk,
            amount_minor=5_000,
        )

        self.campaign.refresh_from_db()
        self.assertEqual(purchase.amount_minor, 5_000)
        self.assertEqual(purchase.payment_method, AdPurchase.PaymentMethod.SIMULATED)
        self.assertEqual(self.campaign.funded_total_minor, 5_000)
        self.assertEqual(self.campaign.status, AdCampaign.Status.ACTIVE)
        self.assertEqual(AdPurchase.objects.count(), 1)

    def test_purchase_and_funded_total_roll_back_together(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                purchase_campaign(
                    actor=self.manager,
                    campaign_id=self.campaign.pk,
                    amount_minor=2_500,
                )
                raise RuntimeError('Abort the surrounding operation.')

        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.funded_total_minor, 0)
        self.assertEqual(AdPurchase.objects.count(), 0)

    def test_another_manager_cannot_fund_the_campaign(self):
        with self.assertRaises(PermissionDenied):
            purchase_campaign(
                actor=self.other_manager,
                campaign_id=self.campaign.pk,
                amount_minor=1_000,
            )

    def test_members_cannot_fund_campaigns(self):
        with self.assertRaises(PermissionDenied):
            purchase_campaign(
                actor=self.member,
                campaign_id=self.campaign.pk,
                amount_minor=1_000,
            )

    def test_staff_need_explicit_campaign_permission(self):
        with self.assertRaises(PermissionDenied):
            purchase_campaign(
                actor=self.staff,
                campaign_id=self.campaign.pk,
                amount_minor=1_000,
            )

        permission = Permission.objects.get(
            content_type__app_label='advertising',
            codename='change_adcampaign',
        )
        self.staff.user_permissions.add(permission)
        staff_with_permission = User.objects.get(pk=self.staff.pk)
        purchase = purchase_campaign(
            actor=staff_with_permission,
            campaign_id=self.campaign.pk,
            amount_minor=1_000,
        )

        self.assertEqual(purchase.purchaser, staff_with_permission)

    def test_campaign_permission_without_staff_status_is_not_enough(self):
        permission = Permission.objects.get(
            content_type__app_label='advertising',
            codename='change_adcampaign',
        )
        self.member.user_permissions.add(permission)
        member_with_permission = User.objects.get(pk=self.member.pk)

        with self.assertRaises(PermissionDenied):
            purchase_campaign(
                actor=member_with_permission,
                campaign_id=self.campaign.pk,
                amount_minor=1_000,
            )

    def test_invalid_purchase_amounts_do_not_change_the_balance(self):
        invalid_amounts = (0, -1, 1.5, True, 10_000_001)

        for amount in invalid_amounts:
            with self.subTest(amount=amount):
                with self.assertRaises(ValidationError):
                    purchase_campaign(
                        actor=self.manager,
                        campaign_id=self.campaign.pk,
                        amount_minor=amount,
                    )

        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.funded_total_minor, 0)
        self.assertEqual(AdPurchase.objects.count(), 0)

    def test_ended_campaign_cannot_be_funded(self):
        self.campaign.status = AdCampaign.Status.ENDED
        self.campaign.save(update_fields=('status',))

        with self.assertRaises(CampaignNotEligible):
            purchase_campaign(
                actor=self.manager,
                campaign_id=self.campaign.pk,
                amount_minor=1_000,
            )

    def test_invalid_campaign_dates_are_rejected_by_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AdCampaign.objects.create(
                    owner=self.manager,
                    name='Invalid date window',
                    starts_at=self.campaign.ends_at,
                    ends_at=self.campaign.starts_at,
                )

    def test_campaign_owner_must_be_an_ad_manager(self):
        campaign = AdCampaign(
            owner=self.member,
            name='Member campaign',
            starts_at=self.campaign.starts_at,
            ends_at=self.campaign.ends_at,
        )

        with self.assertRaises(ValidationError):
            campaign.full_clean()

    def test_campaign_status_transitions_are_authorized_and_validated(self):
        purchase_campaign(
            actor=self.manager,
            campaign_id=self.campaign.pk,
            amount_minor=1_000,
        )
        transition_campaign_status(
            actor=self.manager,
            campaign_id=self.campaign.pk,
            status=AdCampaign.Status.PAUSED,
        )
        transition_campaign_status(
            actor=self.manager,
            campaign_id=self.campaign.pk,
            status=AdCampaign.Status.ACTIVE,
        )
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, AdCampaign.Status.ACTIVE)

        with self.assertRaises(ValidationError):
            transition_campaign_status(
                actor=self.manager,
                campaign_id=self.campaign.pk,
                status=AdCampaign.Status.DRAFT,
            )

    def test_impression_updates_spend_and_retry_is_idempotent(self):
        purchase_campaign(
            actor=self.manager,
            campaign_id=self.campaign.pk,
            amount_minor=1_000,
        )

        impression = charge_impression(
            viewer=self.member,
            creative_id=self.creative.pk,
            idempotency_key='feed-slot-1',
        )
        retry = charge_impression(
            viewer=self.member,
            creative_id=self.creative.pk,
            idempotency_key='feed-slot-1',
        )

        self.campaign.refresh_from_db()
        self.assertEqual(retry.pk, impression.pk)
        self.assertEqual(AdImpression.objects.count(), 1)
        self.assertEqual(impression.charged_amount_minor, 100)
        self.assertEqual(self.campaign.spent_total_minor, 100)

    def test_impression_charge_and_spend_roll_back_together(self):
        purchase_campaign(
            actor=self.manager,
            campaign_id=self.campaign.pk,
            amount_minor=1_000,
        )

        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                charge_impression(
                    viewer=self.member,
                    creative_id=self.creative.pk,
                    idempotency_key='rolled-back-impression',
                )
                raise RuntimeError('Abort the surrounding operation.')

        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.spent_total_minor, 0)
        self.assertEqual(AdImpression.objects.count(), 0)

    def test_impression_cannot_exceed_funded_budget(self):
        self.campaign.impression_cost_minor = 101
        self.campaign.save(update_fields=('impression_cost_minor',))
        purchase_campaign(
            actor=self.manager,
            campaign_id=self.campaign.pk,
            amount_minor=100,
        )

        with self.assertRaises(InsufficientBudget):
            charge_impression(
                viewer=self.member,
                creative_id=self.creative.pk,
                idempotency_key='too-expensive',
            )

        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.spent_total_minor, 0)
        self.assertEqual(AdImpression.objects.count(), 0)

    def test_impression_requires_active_approved_creative(self):
        purchase_campaign(
            actor=self.manager,
            campaign_id=self.campaign.pk,
            amount_minor=1_000,
        )
        self.creative.is_approved = False
        self.creative.save(update_fields=('is_approved',))

        with self.assertRaises(CampaignNotEligible):
            charge_impression(
                viewer=self.member,
                creative_id=self.creative.pk,
                idempotency_key='unapproved-ad',
            )

    def test_reusing_impression_key_for_another_creative_is_rejected(self):
        second_creative = AdCreative.objects.create(
            campaign=self.campaign,
            headline='Another ad',
            body='Second creative.',
            destination_url='https://example.test/second',
            is_active=True,
            is_approved=True,
        )
        purchase_campaign(
            actor=self.manager,
            campaign_id=self.campaign.pk,
            amount_minor=1_000,
        )
        charge_impression(
            viewer=self.member,
            creative_id=self.creative.pk,
            idempotency_key='reused-key',
        )

        with self.assertRaises(IdempotencyConflict):
            charge_impression(
                viewer=self.member,
                creative_id=second_creative.pk,
                idempotency_key='reused-key',
            )
