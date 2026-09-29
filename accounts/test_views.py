from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse


class AccountViewTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_registration_always_creates_a_member(self):
        response = self.client.get(reverse('accounts:register'))
        csrf_token = response.cookies['csrftoken'].value

        response = self.client.post(
            reverse('accounts:register'),
            {
                'username': 'new-ad-manager',
                'password1': 'Member-password-9182!',
                'password2': 'Member-password-9182!',
                'user_type': 'ad_manager',
            },
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        user = get_user_model().objects.get(username='new-ad-manager')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/')
        self.assertEqual(user.user_type, get_user_model().UserType.MEMBER)

    def test_registration_post_requires_csrf(self):
        response = self.client.post(
            reverse('accounts:register'),
            {
                'username': 'csrf-member',
                'password1': 'Member-password-9182!',
                'password2': 'Member-password-9182!',
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_login_and_logout_use_csrf_protected_post_requests(self):
        user = get_user_model().objects.create_user(
            username='login-member',
            password='Member-password-9182!',
        )
        login_page = self.client.get(reverse('accounts:login'))
        csrf_token = login_page.cookies['csrftoken'].value

        login_response = self.client.post(
            reverse('accounts:login'),
            {'username': user.username, 'password': 'Member-password-9182!'},
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_response['Location'], '/')
        self.assertEqual(
            self.client.get(reverse('accounts:logout')).status_code,
            405,
        )
        logout_response = self.client.post(
            reverse('accounts:logout'),
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value,
        )
        self.assertRedirects(logout_response, reverse('accounts:login'))
