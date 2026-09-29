from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AdCampaign, AdCreative, AdPurchase

User = get_user_model()


class AdvertisingViewTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username='dashboard-manager',
            user_type=User.UserType.AD_MANAGER,
        )
        self.other_manager = User.objects.create_user(
            username='other-dashboard-manager',
            user_type=User.UserType.AD_MANAGER,
        )
        self.member = User.objects.create_user(username='dashboard-member')
        self.now = timezone.now()
        self.campaign = self.make_campaign(self.manager, 'Manager campaign')
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.manager)

    def make_campaign(self, owner, name):
        return AdCampaign.objects.create(
            owner=owner,
            name=name,
            starts_at=self.now - timedelta(days=1),
            ends_at=self.now + timedelta(days=10),
        )

    def csrf_token(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.cookies['csrftoken'].value

    def test_logged_out_dashboard_redirects_to_login(self):
        response = Client().get(reverse('advertising:dashboard'))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith('/accounts/login/'))

    def test_member_cannot_access_dashboard_or_create_campaigns(self):
        self.client.force_login(self.member)

        dashboard = self.client.get(reverse('advertising:dashboard'))
        create = self.client.get(reverse('advertising:campaign_create'))

        self.assertEqual(dashboard.status_code, 403)
        self.assertEqual(create.status_code, 403)

    def test_manager_can_create_campaign_owned_by_the_authenticated_account(self):
        url = reverse('advertising:campaign_create')
        csrf_token = self.csrf_token(url)
        starts_at = timezone.localtime(self.now + timedelta(days=1)).strftime(
            '%Y-%m-%dT%H:%M'
        )
        ends_at = timezone.localtime(self.now + timedelta(days=7)).strftime(
            '%Y-%m-%dT%H:%M'
        )

        response = self.client.post(
            url,
            {
                'name': 'Created in dashboard',
                'starts_at': starts_at,
                'ends_at': ends_at,
                'currency_code': 'USD',
                'impression_cost_minor': 125,
            },
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        campaign = AdCampaign.objects.get(name='Created in dashboard')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(campaign.owner, self.manager)
        self.assertEqual(campaign.status, AdCampaign.Status.DRAFT)

    def test_owner_can_edit_campaign_details_without_editing_ledger_balances(self):
        self.campaign.funded_total_minor = 4_000
        self.campaign.save(update_fields=('funded_total_minor',))
        url = reverse('advertising:campaign_edit', args=(self.campaign.pk,))
        csrf_token = self.csrf_token(url)
        starts_at = timezone.localtime(self.now + timedelta(days=2)).strftime(
            '%Y-%m-%dT%H:%M'
        )
        ends_at = timezone.localtime(self.now + timedelta(days=8)).strftime(
            '%Y-%m-%dT%H:%M'
        )

        response = self.client.post(
            url,
            {
                'name': 'Updated campaign name',
                'starts_at': starts_at,
                'ends_at': ends_at,
                'currency_code': 'USD',
                'impression_cost_minor': 200,
            },
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.campaign.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.campaign.name, 'Updated campaign name')
        self.assertEqual(self.campaign.funded_total_minor, 4_000)
        self.assertEqual(self.campaign.owner, self.manager)

    def test_owner_can_pause_and_resume_campaign_with_post_actions(self):
        self.campaign.funded_total_minor = 1_000
        self.campaign.status = AdCampaign.Status.ACTIVE
        self.campaign.save(update_fields=('funded_total_minor', 'status'))
        url = reverse('advertising:campaign_status', args=(self.campaign.pk,))
        csrf_token = self.csrf_token(reverse('advertising:dashboard'))

        pause_response = self.client.post(
            url,
            {'status': AdCampaign.Status.PAUSED},
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.campaign.refresh_from_db()
        self.assertEqual(pause_response.status_code, 302)
        self.assertEqual(self.campaign.status, AdCampaign.Status.PAUSED)

        resume_response = self.client.post(
            url,
            {'status': AdCampaign.Status.ACTIVE},
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.campaign.refresh_from_db()
        self.assertEqual(resume_response.status_code, 302)
        self.assertEqual(self.campaign.status, AdCampaign.Status.ACTIVE)

    def test_dashboard_shows_remaining_budget_and_simulated_purchase_disclosure(self):
        self.campaign.funded_total_minor = 5_000
        self.campaign.spent_total_minor = 1_250
        self.campaign.status = AdCampaign.Status.ACTIVE
        self.campaign.save(
            update_fields=('funded_total_minor', 'spent_total_minor', 'status')
        )

        response = self.client.get(reverse('advertising:dashboard'))

        self.assertContains(response, 'Manager campaign')
        self.assertContains(response, 'USD 37.50')
        self.assertContains(response, 'No payment will be processed')

    def test_dashboard_renders_empty_campaign_state(self):
        self.campaign.delete()

        response = self.client.get(reverse('advertising:dashboard'))

        self.assertContains(response, 'No campaigns yet.')

    def test_campaign_owner_can_purchase_simulated_funding_with_csrf(self):
        url = reverse('advertising:campaign_purchase', args=(self.campaign.pk,))
        csrf_token = self.csrf_token(reverse('advertising:dashboard'))

        response = self.client.post(
            url,
            {'amount_minor': 2_500},
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        dashboard_response = self.client.get(response['Location'])

        self.campaign.refresh_from_db()
        purchase = AdPurchase.objects.get(campaign=self.campaign)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.campaign.funded_total_minor, 2_500)
        self.assertEqual(purchase.payment_method, AdPurchase.PaymentMethod.SIMULATED)
        self.assertContains(dashboard_response, 'Simulated funding added: 2,500 USD minor units')
        self.assertContains(dashboard_response, 'USD 25.00')

    def test_campaign_purchase_rejects_missing_csrf(self):
        response = self.client.post(
            reverse('advertising:campaign_purchase', args=(self.campaign.pk,)),
            {'amount_minor': 2_500},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(AdPurchase.objects.exists())

    def test_owner_isolation_and_authorized_staff_access(self):
        other_campaign = self.make_campaign(self.other_manager, 'Other campaign')
        other_purchase_url = reverse(
            'advertising:campaign_purchase',
            args=(other_campaign.pk,),
        )
        csrf_token = self.csrf_token(reverse('advertising:dashboard'))
        self.assertEqual(
            self.client.post(
                other_purchase_url,
                {'amount_minor': 500},
                HTTP_X_CSRFTOKEN=csrf_token,
            ).status_code,
            403,
        )

        staff = User.objects.create_user(
            username='campaign-staff',
            is_staff=True,
        )
        permission = Permission.objects.get(
            content_type__app_label='advertising',
            codename='change_adcampaign',
        )
        staff.user_permissions.add(permission)
        self.client.force_login(User.objects.get(pk=staff.pk))
        csrf_token = self.csrf_token(reverse('advertising:dashboard'))
        response = self.client.post(
            other_purchase_url,
            {'amount_minor': 500},
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        other_campaign.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(other_campaign.funded_total_minor, 500)

    def test_owner_can_create_a_pending_creative(self):
        url = reverse('advertising:creative_create', args=(self.campaign.pk,))
        csrf_token = self.csrf_token(url)

        response = self.client.post(
            url,
            {
                'headline': 'A new creative',
                'body': 'Ad copy',
                'destination_url': 'https://example.test/new',
                'is_active': 'on',
            },
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        creative = AdCreative.objects.get(campaign=self.campaign)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(creative.is_approved)

    def test_manager_cannot_edit_another_managers_campaign_or_creative(self):
        other_campaign = self.make_campaign(self.other_manager, 'Private campaign')
        creative = AdCreative.objects.create(
            campaign=other_campaign,
            headline='Private creative',
            destination_url='https://example.test/private',
        )

        campaign_response = self.client.get(
            reverse('advertising:campaign_edit', args=(other_campaign.pk,))
        )
        creative_response = self.client.get(
            reverse('advertising:creative_edit', args=(creative.pk,))
        )

        self.assertEqual(campaign_response.status_code, 403)
        self.assertEqual(creative_response.status_code, 403)
