from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AdCampaign


class AdvertisingAdminTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username='advertising-admin',
            password='test-admin-password-9182',
        )
        self.client.force_login(self.admin)

    def test_campaign_creative_purchase_and_impression_admin_pages_load(self):
        for model_name in ('adcampaign', 'adcreative', 'adpurchase', 'adimpression'):
            with self.subTest(model=model_name):
                response = self.client.get(
                    reverse(f'admin:advertising_{model_name}_changelist')
                )
                self.assertEqual(response.status_code, 200)

    def test_campaign_funding_aggregates_are_read_only_in_admin(self):
        owner = get_user_model().objects.create_user(
            username='advertiser',
            user_type=get_user_model().UserType.AD_MANAGER,
        )
        now = timezone.now()
        campaign = AdCampaign.objects.create(
            owner=owner,
            name='Admin campaign',
            starts_at=now,
            ends_at=now + timedelta(days=1),
        )

        response = self.client.get(
            reverse('admin:advertising_adcampaign_change', args=(campaign.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="funded_total_minor"')
        self.assertNotContains(response, 'name="spent_total_minor"')
