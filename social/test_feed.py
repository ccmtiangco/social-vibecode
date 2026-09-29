from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from advertising.models import AdCampaign, AdCreative
from .models import Follow, Post
from .services import create_post
from .feed import InvalidFeedCursor, get_feed_page


class FeedServiceTests(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user(username='feed-viewer')
        self.followed = User.objects.create_user(username='followed-author')
        self.outsider = User.objects.create_user(username='unfollowed-author')
        Follow.objects.create(follower=self.viewer, followed=self.followed)

    def create_post(self, author, body, created_at=None):
        post = create_post(author=author, body=body)
        if created_at:
            Post.objects.filter(pk=post.pk).update(created_at=created_at)
            post.refresh_from_db()
        return post

    def test_feed_requires_an_active_authenticated_viewer(self):
        inactive_viewer = User.objects.create_user(
            username='inactive-viewer',
            is_active=False,
        )

        with self.assertRaises(PermissionDenied):
            get_feed_page(viewer=AnonymousUser())
        with self.assertRaises(PermissionDenied):
            get_feed_page(viewer=inactive_viewer)

    def create_ad(
        self,
        name,
        *,
        status=AdCampaign.Status.ACTIVE,
        funded=1_000,
        spent=0,
        starts_at=None,
        ends_at=None,
        creative_count=1,
    ):
        now = timezone.now()
        owner = User.objects.create_user(
            username=f'manager-{name}',
            user_type=User.UserType.AD_MANAGER,
        )
        campaign = AdCampaign.objects.create(
            owner=owner,
            name=name,
            status=status,
            starts_at=starts_at or now - timedelta(days=1),
            ends_at=ends_at or now + timedelta(days=1),
            funded_total_minor=funded,
            spent_total_minor=spent,
            impression_cost_minor=100,
        )
        return [
            AdCreative.objects.create(
                campaign=campaign,
                headline=f'{name} creative {index}',
                body='Sponsored copy.',
                destination_url='https://example.test/ad',
                is_active=True,
                is_approved=True,
            )
            for index in range(creative_count)
        ]

    @override_settings(FEED_MAX_ADS_PER_PAGE=0)
    def test_feed_is_chronological_and_uses_id_to_break_timestamp_ties(self):
        timestamp = timezone.now() - timedelta(hours=1)
        oldest = self.create_post(self.viewer, 'Oldest', timestamp - timedelta(minutes=1))
        tied_first = self.create_post(self.followed, 'Tied first', timestamp)
        tied_second = self.create_post(self.viewer, 'Tied second', timestamp)
        newest = self.create_post(self.followed, 'Newest', timestamp + timedelta(minutes=1))
        self.create_post(self.outsider, 'Not in this feed', timestamp + timedelta(minutes=2))

        page = get_feed_page(viewer=self.viewer)

        self.assertEqual(
            [entry.post.pk for entry in page.entries],
            [newest.pk, tied_second.pk, tied_first.pk, oldest.pk],
        )

    @override_settings(FEED_MAX_ADS_PER_PAGE=0)
    def test_feed_includes_own_and_followed_posts_but_not_unfollowed_posts(self):
        own = self.create_post(self.viewer, 'Mine')
        followed = self.create_post(self.followed, 'Followed')
        self.create_post(self.outsider, 'Outside graph')

        page = get_feed_page(viewer=self.viewer)

        self.assertEqual(
            {entry.post.pk for entry in page.entries},
            {own.pk, followed.pk},
        )

    @override_settings(FEED_MAX_ADS_PER_PAGE=0)
    def test_reshares_are_feed_activities_ordered_by_their_own_timestamp(self):
        now = timezone.now()
        original = self.create_post(
            self.followed,
            'Original post',
            now - timedelta(minutes=1),
        )
        reshare = create_post(
            author=self.viewer,
            body='Adding a comment',
            reshared_post=original,
        )
        Post.objects.filter(pk=reshare.pk).update(created_at=now)

        page = get_feed_page(viewer=self.viewer)

        self.assertEqual([entry.post.pk for entry in page.entries], [reshare.pk, original.pk])
        self.assertEqual(page.entries[0].post.reshared_post_id, original.pk)

    @override_settings(FEED_MAX_ADS_PER_PAGE=0)
    def test_keyset_cursor_continues_without_skipping_or_repeating_posts(self):
        timestamp = timezone.now()
        posts = [
            self.create_post(
                self.followed if index % 2 else self.viewer,
                f'Post {index}',
                timestamp + timedelta(seconds=index),
            )
            for index in range(5)
        ]
        expected = [post.pk for post in reversed(posts)]

        first_page = get_feed_page(viewer=self.viewer, page_size=2)
        second_page = get_feed_page(
            viewer=self.viewer,
            cursor=first_page.next_cursor,
            page_size=2,
        )
        third_page = get_feed_page(
            viewer=self.viewer,
            cursor=second_page.next_cursor,
            page_size=2,
        )

        actual = [
            entry.post.pk
            for page in (first_page, second_page, third_page)
            for entry in page.entries
        ]
        self.assertEqual(actual, expected)
        self.assertTrue(first_page.has_next)
        self.assertTrue(second_page.has_next)
        self.assertFalse(third_page.has_next)
        self.assertIsNone(third_page.next_cursor)

    @override_settings(FEED_MAX_ADS_PER_PAGE=0)
    def test_cursor_is_signed_and_bound_to_the_viewer(self):
        self.create_post(self.viewer, 'Cursor source')
        self.create_post(self.followed, 'Cursor continuation')
        page = get_feed_page(viewer=self.viewer, page_size=1)
        other_viewer = User.objects.create_user(username='different-viewer')

        with self.assertRaises(InvalidFeedCursor):
            get_feed_page(viewer=self.viewer, cursor=f'{page.next_cursor}tampered')
        with self.assertRaises(InvalidFeedCursor):
            get_feed_page(viewer=other_viewer, cursor=page.next_cursor)

    @override_settings(
        FEED_AD_INTERVAL=2,
        FEED_MAX_ADS_PER_PAGE=2,
        FEED_PAGE_SIZE=8,
    )
    def test_ads_are_interleaved_at_interval_and_capped_per_page(self):
        for index in range(9):
            self.create_post(self.followed, f'Organic {index}')
        creatives = [
            creative
            for ad_index in range(3)
            for creative in self.create_ad(f'campaign-{ad_index}')
        ]

        page = get_feed_page(viewer=self.viewer)
        positions = [
            index
            for index, entry in enumerate(page.entries, start=1)
            if entry.is_sponsored
        ]

        self.assertEqual(positions, [3, 6])
        self.assertEqual(sum(entry.is_sponsored for entry in page.entries), 2)
        self.assertEqual(
            len({entry.creative.pk for entry in page.entries if entry.is_sponsored}),
            2,
        )
        self.assertEqual(
            [entry.label for entry in page.entries if entry.is_sponsored],
            ['Sponsored', 'Sponsored'],
        )
        self.assertTrue(page.has_next)
        self.assertEqual(len(creatives), 3)

    @override_settings(
        FEED_AD_INTERVAL=2,
        FEED_MAX_ADS_PER_PAGE=2,
        FEED_PAGE_SIZE=2,
    )
    def test_ads_do_not_advance_organic_cursor_and_campaigns_are_frequency_capped(self):
        posts = [
            self.create_post(self.followed, f'Organic {index}')
            for index in range(6)
        ]
        first_campaign_creative = self.create_ad('first-campaign')[0]
        second_campaign_creative = self.create_ad('second-campaign')[0]

        first_page = get_feed_page(viewer=self.viewer)
        second_page = get_feed_page(
            viewer=self.viewer,
            cursor=first_page.next_cursor,
        )
        third_page = get_feed_page(
            viewer=self.viewer,
            cursor=second_page.next_cursor,
        )

        self.assertEqual(first_page.entries[0].post.pk, posts[-1].pk)
        self.assertEqual(first_page.entries[1].post.pk, posts[-2].pk)
        self.assertEqual(first_page.entries[2].creative.pk, first_campaign_creative.pk)
        self.assertEqual(second_page.entries[0].post.pk, posts[-3].pk)
        self.assertEqual(second_page.entries[1].post.pk, posts[-4].pk)
        self.assertEqual(second_page.entries[2].creative.pk, second_campaign_creative.pk)
        self.assertEqual(third_page.entries[0].post.pk, posts[-5].pk)
        self.assertFalse(any(entry.is_sponsored for entry in third_page.entries))

    @override_settings(FEED_AD_INTERVAL=2, FEED_MAX_ADS_PER_PAGE=4, FEED_PAGE_SIZE=8)
    def test_paused_expired_and_exhausted_campaigns_are_excluded(self):
        for index in range(8):
            self.create_post(self.followed, f'Organic {index}')
        eligible = self.create_ad('eligible')[0]
        paused = self.create_ad('paused', status=AdCampaign.Status.PAUSED)[0]
        exhausted = self.create_ad('exhausted', funded=100, spent=100)[0]
        expired = self.create_ad(
            'expired',
            ends_at=timezone.now() - timedelta(minutes=1),
        )[0]

        page = get_feed_page(viewer=self.viewer)
        sponsored = [entry.creative.pk for entry in page.entries if entry.is_sponsored]

        self.assertEqual(sponsored, [eligible.pk])
        self.assertNotIn(paused.pk, sponsored)
        self.assertNotIn(exhausted.pk, sponsored)
        self.assertNotIn(expired.pk, sponsored)

    @override_settings(FEED_AD_INTERVAL=2, FEED_MAX_ADS_PER_PAGE=4, FEED_PAGE_SIZE=8)
    def test_no_eligible_ads_leaves_the_feed_organic_only(self):
        for index in range(8):
            self.create_post(self.followed, f'Organic {index}')
        self.create_ad('paused-only', status=AdCampaign.Status.PAUSED)
        self.create_ad('spent-only', funded=100, spent=100)

        page = get_feed_page(viewer=self.viewer)

        self.assertEqual(len(page.entries), 8)
        self.assertFalse(any(entry.is_sponsored for entry in page.entries))

    @override_settings(FEED_MAX_ADS_PER_PAGE=0)
    def test_feed_page_prefetches_authors_reshared_originals_and_images(self):
        original = self.create_post(self.followed, 'Original')
        create_post(author=self.viewer, body='Reshare activity', reshared_post=original)

        with self.assertNumQueries(2):
            page = get_feed_page(viewer=self.viewer, page_size=10)
            for entry in page.entries:
                _ = entry.post.author.username
                if entry.post.reshared_post_id:
                    _ = entry.post.reshared_post.author.username
                list(entry.post.images.all())
