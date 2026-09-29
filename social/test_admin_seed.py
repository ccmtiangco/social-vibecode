from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Follow, Post, PostImage

User = get_user_model()


class SocialAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='social-admin',
            password='test-admin-password-9182',
        )
        self.client.force_login(self.admin)

    def test_users_posts_images_and_follows_are_available_in_admin(self):
        for model_name in ('user', 'post', 'postimage', 'follow'):
            response = self.client.get(
                reverse(f'admin:social_{model_name}_changelist')
                if model_name != 'user'
                else reverse('admin:accounts_user_changelist')
            )

            self.assertEqual(response.status_code, 200, model_name)

    def test_admin_add_uses_the_custom_user_and_defaults_to_member(self):
        response = self.client.get(reverse('admin:accounts_user_add'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="user_type"')

    def test_superuser_can_manage_account_type(self):
        member = User.objects.create_user(username='admin-managed-member')

        response = self.client.get(
            reverse('admin:accounts_user_change', args=(member.pk,))
        )

        self.assertContains(response, 'name="user_type"')

    def test_non_superuser_staff_cannot_change_account_type(self):
        member = User.objects.create_user(username='staff-managed-member')
        staff = User.objects.create_user(
            username='social-staff',
            password='test-staff-password-9182',
            is_staff=True,
        )
        change_user = Permission.objects.get(
            content_type__app_label='accounts',
            codename='change_user',
        )
        staff.user_permissions.add(change_user)
        self.client.force_login(staff)

        response = self.client.get(
            reverse('admin:accounts_user_change', args=(member.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="user_type"')


class SeedSocialDataTests(TestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        media_settings = override_settings(MEDIA_ROOT=self.media_directory.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)

    @override_settings(DEBUG=True)
    def test_seed_command_is_idempotent_and_creates_demo_media(self):
        call_command('seed_social_data')
        call_command('seed_social_data')

        self.assertEqual(User.objects.filter(username__startswith='demo_').count(), 3)
        self.assertEqual(Follow.objects.count(), 3)
        self.assertEqual(Post.objects.count(), 3)
        self.assertEqual(PostImage.objects.count(), 1)
        self.assertFalse(
            any(
                user.has_usable_password()
                for user in User.objects.filter(username__startswith='demo_')
            )
        )
        image = PostImage.objects.get()
        self.assertTrue(Path(self.media_directory.name, image.image.name).is_file())

    @override_settings(DEBUG=False)
    def test_seed_command_refuses_to_run_outside_debug_mode(self):
        with self.assertRaises(CommandError):
            call_command('seed_social_data')
