from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.handlers.wsgi import WSGIHandler
from django.test import Client, RequestFactory, TestCase, override_settings
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import User
from advertising.models import AdCampaign, AdCreative
from .models import Follow, Post, PostImage
from .services import create_post


class SocialViewTests(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user(username='social-viewer')
        self.other = User.objects.create_user(username='social-other')
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.viewer)

    def csrf_token(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.cookies['csrftoken'].value

    def image_upload(self, name):
        output = BytesIO()
        Image.new('RGB', (8, 8), color='teal').save(output, format='PNG')
        return SimpleUploadedFile(name, output.getvalue(), content_type='image/png')

    def test_logged_out_users_are_redirected_from_private_social_pages(self):
        client = Client()
        post = create_post(author=self.other, body='Share me')
        urls = (
            reverse('social:feed'),
            reverse('social:post_create'),
            reverse('social:follow', args=(self.other.username,)),
            reverse('social:reshare', args=(post.pk,)),
        )

        for url in urls:
            with self.subTest(url=url):
                response = client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response['Location'].startswith('/accounts/login/'))

    def test_feed_and_empty_profile_render_empty_states(self):
        feed_response = self.client.get(reverse('social:feed'))
        profile_response = self.client.get(
            reverse('social:profile', args=(self.other.username,))
        )

        self.assertContains(feed_response, 'Your feed starts here.')
        self.assertContains(profile_response, 'No posts yet.')

    def test_nested_pages_use_the_discoverable_root_static_stylesheet_url(self):
        response = self.client.get(
            reverse('social:profile', args=(self.other.username,))
        )

        self.assertContains(response, 'href="/static/social/site.css"')
        self.assertIsNotNone(finders.find('social/site.css'))

    def test_debug_static_url_serves_the_stylesheet(self):
        state = {}

        def start_response(status, headers, exc_info=None):
            state['status'] = status
            state['headers'] = dict(headers)

        request = RequestFactory().get(static('social/site.css'))
        body = b''.join(
            StaticFilesHandler(WSGIHandler())(request.environ, start_response)
        )

        self.assertEqual(state['status'], '200 OK')
        self.assertTrue(state['headers']['Content-Type'].startswith('text/css'))
        self.assertIn(b'.site-header', body)

    def test_feed_renders_eligible_creatives_as_sponsored(self):
        now = timezone.now()
        manager = User.objects.create_user(
            username='feed-ad-manager',
            user_type=User.UserType.AD_MANAGER,
        )
        campaign = AdCampaign.objects.create(
            owner=manager,
            name='Garden campaign',
            status=AdCampaign.Status.ACTIVE,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=1),
            funded_total_minor=1_000,
            impression_cost_minor=100,
        )
        AdCreative.objects.create(
            campaign=campaign,
            headline='A gentler garden tool',
            body='Sponsored copy',
            destination_url='https://example.test/garden',
            is_active=True,
            is_approved=True,
        )
        for index in range(8):
            create_post(author=self.viewer, body=f'Feed note {index}')

        response = self.client.get(reverse('social:feed'))

        self.assertContains(response, 'Sponsored')
        self.assertContains(response, 'A gentler garden tool')

    def test_feed_template_exposes_keyset_pagination(self):
        for index in range(21):
            create_post(author=self.viewer, body=f'Older feed note {index}')

        response = self.client.get(reverse('social:feed'))

        self.assertContains(response, 'Older posts')
        self.assertContains(response, 'cursor=')

    def test_post_creation_accepts_multiple_images_through_csrf_protected_post(self):
        url = reverse('social:post_create')
        page = self.client.get(url)
        csrf_token = page.cookies['csrftoken'].value
        self.assertContains(page, 'multiple')

        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                url,
                {
                    'body': 'A small photo set',
                    'images': [self.image_upload('first.png'), self.image_upload('second.png')],
                },
                HTTP_X_CSRFTOKEN=csrf_token,
            )
            feed_response = self.client.get(reverse('social:feed'))

        post = Post.objects.get(author=self.viewer)
        self.assertRedirects(response, reverse('social:feed'))
        self.assertEqual(post.images.count(), 2)
        self.assertEqual(PostImage.objects.count(), 2)
        self.assertContains(feed_response, 'alt="social-viewer"', count=2)

    def test_post_creation_rejects_missing_csrf_and_empty_content(self):
        url = reverse('social:post_create')

        csrf_failure = self.client.post(url, {'body': 'No token'})
        self.assertEqual(csrf_failure.status_code, 403)

        csrf_token = self.csrf_token(url)
        empty_post = self.client.post(
            url,
            {'body': '   '},
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(empty_post.status_code, 200)
        self.assertEqual(Post.objects.count(), 0)

    def test_follow_and_unfollow_are_post_only_and_csrf_protected(self):
        follow_url = reverse('social:follow', args=(self.other.username,))
        csrf_token = self.csrf_token(reverse('social:profile', args=(self.other.username,)))

        self.assertEqual(self.client.get(follow_url).status_code, 405)
        self.assertEqual(self.client.post(follow_url).status_code, 403)

        follow_response = self.client.post(follow_url, HTTP_X_CSRFTOKEN=csrf_token)
        self.assertRedirects(
            follow_response,
            reverse('social:profile', args=(self.other.username,)),
        )
        self.assertTrue(
            Follow.objects.filter(follower=self.viewer, followed=self.other).exists()
        )

        unfollow_url = reverse('social:unfollow', args=(self.other.username,))
        unfollow_response = self.client.post(
            unfollow_url,
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value,
        )
        self.assertRedirects(
            unfollow_response,
            reverse('social:profile', args=(self.other.username,)),
        )
        self.assertFalse(
            Follow.objects.filter(follower=self.viewer, followed=self.other).exists()
        )

    def test_reshare_is_a_csrf_protected_post_that_references_the_original(self):
        original = create_post(author=self.other, body='Original content')
        url = reverse('social:reshare', args=(original.pk,))
        csrf_token = self.csrf_token(reverse('social:feed'))

        response = self.client.post(
            url,
            {'body': 'My comment'},
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        reshare = Post.objects.get(author=self.viewer, reshared_post=original)
        self.assertRedirects(response, reverse('social:feed'))
        self.assertEqual(reshare.body, 'My comment')
        self.assertEqual(reshare.reshared_post_id, original.pk)

    def test_profile_shows_posts_and_follow_state(self):
        Follow.objects.create(follower=self.viewer, followed=self.other)
        create_post(author=self.other, body='A profile post')

        response = self.client.get(
            reverse('social:profile', args=(self.other.username,))
        )

        self.assertContains(response, 'A profile post')
        self.assertContains(response, 'Unfollow')
