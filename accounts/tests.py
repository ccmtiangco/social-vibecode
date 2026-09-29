from django.test import TestCase
from django.urls import reverse

from .forms import MemberCreationForm
from .models import User


class UserModelTests(TestCase):
    def test_new_users_default_to_member(self):
        user = User.objects.create_user(username='member')

        self.assertEqual(user.user_type, User.UserType.MEMBER)

    def test_user_creation_form_does_not_allow_role_elevation(self):
        form = MemberCreationForm(
            {
                'username': 'new-member',
                'password1': 'correct-horse-battery-staple-9381',
                'password2': 'correct-horse-battery-staple-9381',
                'user_type': User.UserType.AD_MANAGER,
            }
        )

        self.assertNotIn('user_type', form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertEqual(user.user_type, User.UserType.MEMBER)

    def test_ad_manager_role_can_be_assigned_explicitly(self):
        user = User.objects.create_user(
            username='campaign-manager',
            user_type=User.UserType.AD_MANAGER,
        )

        self.assertEqual(user.user_type, User.UserType.AD_MANAGER)

    def test_superuser_can_authenticate_and_access_admin(self):
        user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='correct-horse-battery-staple-9381',
        )

        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(
            self.client.login(
                username='admin',
                password='correct-horse-battery-staple-9381',
            )
        )
        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)
