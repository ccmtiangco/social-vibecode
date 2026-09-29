from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from social.validators import validate_post_image


def creative_image_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    return f'advertising/creatives/{instance.campaign_id}/{uuid4().hex}{extension}'


class AdCampaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        ACTIVE = 'active', 'Active'
        PAUSED = 'paused', 'Paused'
        ENDED = 'ended', 'Ended'

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='ad_campaigns',
        db_index=False,
    )
    name = models.CharField(max_length=200)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    currency_code = models.CharField(max_length=3, default='USD')
    funded_total_minor = models.PositiveBigIntegerField(default=0)
    spent_total_minor = models.PositiveBigIntegerField(default=0)
    impression_cost_minor = models.PositiveBigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F('starts_at')),
                name='advertising_campaign_valid_dates',
            ),
            models.CheckConstraint(
                condition=Q(spent_total_minor__lte=F('funded_total_minor')),
                name='advertising_campaign_spend_within_funding',
            ),
            models.CheckConstraint(
                condition=Q(impression_cost_minor__gt=0),
                name='advertising_campaign_positive_impression_cost',
            ),
        ]
        indexes = [
            models.Index(
                fields=('status', 'starts_at', 'ends_at'),
                name='ad_campaign_elig_idx',
            ),
            models.Index(
                fields=('owner', '-created_at'),
                name='ad_campaign_owner_idx',
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.owner_id
            and self.owner.user_type != get_user_model().UserType.AD_MANAGER
        ):
            raise ValidationError({'owner': 'Campaign owners must be ad managers.'})
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValidationError({'ends_at': 'Campaigns must end after they start.'})
        if self.spent_total_minor > self.funded_total_minor:
            raise ValidationError({'spent_total_minor': 'Spend cannot exceed funding.'})

    @property
    def remaining_minor(self):
        return self.funded_total_minor - self.spent_total_minor

    def __str__(self):
        return self.name


class AdCreative(models.Model):
    campaign = models.ForeignKey(
        AdCampaign,
        on_delete=models.CASCADE,
        related_name='creatives',
    )
    headline = models.CharField(max_length=150)
    body = models.TextField(blank=True)
    image = models.ImageField(
        upload_to=creative_image_upload_to,
        validators=[validate_post_image],
        blank=True,
    )
    destination_url = models.URLField()
    is_active = models.BooleanField(default=True)
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=('campaign', 'is_active', 'is_approved'),
                name='ad_creative_elig_idx',
            ),
        ]

    def __str__(self):
        return self.headline


class AdPurchase(models.Model):
    class PaymentMethod(models.TextChoices):
        SIMULATED = 'simulated', 'Simulated'

    class Status(models.TextChoices):
        COMPLETED = 'completed', 'Completed'

    campaign = models.ForeignKey(
        AdCampaign,
        on_delete=models.PROTECT,
        related_name='purchases',
    )
    purchaser = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='ad_purchases',
    )
    amount_minor = models.PositiveBigIntegerField()
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.SIMULATED,
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.COMPLETED,
    )
    reference = models.UUIDField(default=uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_minor__gt=0),
                name='advertising_purchase_positive_amount',
            ),
        ]
        indexes = [
            models.Index(
                fields=('campaign', '-created_at'),
                name='ad_purchase_campaign_idx',
            ),
        ]

    def __str__(self):
        return f'{self.amount_minor} {self.campaign.currency_code} simulated funding'


class AdImpression(models.Model):
    campaign = models.ForeignKey(
        AdCampaign,
        on_delete=models.PROTECT,
        related_name='impressions',
    )
    creative = models.ForeignKey(
        AdCreative,
        on_delete=models.PROTECT,
        related_name='impressions',
    )
    viewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='ad_impressions',
    )
    idempotency_key = models.CharField(max_length=64)
    charged_amount_minor = models.PositiveBigIntegerField()
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('viewer', 'idempotency_key'),
                name='advertising_impression_viewer_key_unique',
            ),
            models.CheckConstraint(
                condition=Q(charged_amount_minor__gt=0),
                name='advertising_impression_positive_charge',
            ),
        ]
        indexes = [
            models.Index(
                fields=('campaign', '-occurred_at'),
                name='ad_impress_campaign_idx',
            ),
            models.Index(
                fields=('creative', '-occurred_at'),
                name='ad_impress_creative_idx',
            ),
        ]

    def clean(self):
        super().clean()
        if self.campaign_id and self.creative_id:
            if self.creative.campaign_id != self.campaign_id:
                raise ValidationError({'creative': 'Creative must belong to the campaign.'})

    def __str__(self):
        return f'Impression {self.pk} for campaign {self.campaign_id}'
