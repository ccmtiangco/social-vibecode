from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import F, Q
from django.utils import timezone

from advertising.models import AdCampaign, AdCreative

from .models import Follow, Post

CURSOR_SALT = 'social.feed'
CURSOR_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
MAX_FEED_PAGE_SIZE = 100
RECENT_CAMPAIGN_FREQUENCY_CAP = 20


@dataclass(frozen=True)
class FeedEntry:
    post: Post | None = None
    creative: AdCreative | None = None

    def __post_init__(self):
        if (self.post is None) == (self.creative is None):
            raise ValueError('A feed entry must contain exactly one post or ad creative.')

    @property
    def is_sponsored(self):
        return self.creative is not None

    @property
    def label(self):
        return 'Sponsored' if self.is_sponsored else None


@dataclass(frozen=True)
class FeedPage:
    entries: tuple[FeedEntry, ...]
    next_cursor: str | None
    has_next: bool


class InvalidFeedCursor(ValidationError):
    pass


def _decode_cursor(cursor, viewer_id):
    if cursor is None:
        return None, None, ()
    if not isinstance(cursor, str) or len(cursor) > 4096:
        raise InvalidFeedCursor('Invalid feed cursor.')

    try:
        payload = signing.loads(
            cursor,
            salt=CURSOR_SALT,
            max_age=CURSOR_MAX_AGE_SECONDS,
        )
        if payload['viewer_id'] != viewer_id:
            raise InvalidFeedCursor('Feed cursor belongs to another viewer.')
        created_at = datetime.fromisoformat(payload['created_at'])
        post_id = payload['post_id']
        recent_campaign_ids = payload['recent_campaign_ids']
        if (
            timezone.is_naive(created_at)
            or not isinstance(post_id, int)
            or post_id < 1
            or not isinstance(recent_campaign_ids, list)
            or len(recent_campaign_ids) > RECENT_CAMPAIGN_FREQUENCY_CAP
            or any(
                not isinstance(campaign_id, int) or campaign_id < 1
                for campaign_id in recent_campaign_ids
            )
        ):
            raise InvalidFeedCursor('Invalid feed cursor.')
    except (signing.BadSignature, KeyError, TypeError, ValueError) as error:
        raise InvalidFeedCursor('Invalid or expired feed cursor.') from error

    return created_at, post_id, tuple(dict.fromkeys(recent_campaign_ids))


def _encode_cursor(*, viewer_id, post, recent_campaign_ids):
    recent_campaign_ids = list(dict.fromkeys(recent_campaign_ids))
    payload = {
        'viewer_id': viewer_id,
        'created_at': post.created_at.isoformat(),
        'post_id': post.pk,
        'recent_campaign_ids': recent_campaign_ids[-RECENT_CAMPAIGN_FREQUENCY_CAP:],
    }
    return signing.dumps(payload, salt=CURSOR_SALT)


def _eligible_ad_creatives(*, now, campaign_ids, limit):
    candidates = AdCreative.objects.filter(
        is_active=True,
        is_approved=True,
        campaign__status=AdCampaign.Status.ACTIVE,
        campaign__starts_at__lte=now,
        campaign__ends_at__gt=now,
        campaign__funded_total_minor__gte=(
            F('campaign__spent_total_minor') + F('campaign__impression_cost_minor')
        ),
    )
    if campaign_ids:
        candidates = candidates.exclude(campaign_id__in=campaign_ids)
    return list(candidates.select_related('campaign').order_by('pk')[:limit])


def get_feed_page(*, viewer, cursor=None, page_size=None):
    if (
        not viewer
        or not getattr(viewer, 'is_authenticated', False)
        or not getattr(viewer, 'is_active', False)
        or viewer.pk is None
    ):
        raise PermissionDenied('An active authenticated user is required for the feed.')

    page_size = settings.FEED_PAGE_SIZE if page_size is None else page_size
    ad_interval = settings.FEED_AD_INTERVAL
    max_ads = settings.FEED_MAX_ADS_PER_PAGE
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= MAX_FEED_PAGE_SIZE
        or isinstance(ad_interval, bool)
        or not isinstance(ad_interval, int)
        or ad_interval < 1
        or isinstance(max_ads, bool)
        or not isinstance(max_ads, int)
        or max_ads < 0
    ):
        raise ValidationError('Feed page, ad interval, or ad cap configuration is invalid.')

    cursor_created_at, cursor_post_id, recent_campaign_ids = _decode_cursor(
        cursor,
        viewer.pk,
    )
    followed_ids = Follow.objects.filter(follower_id=viewer.pk).values('followed_id')
    organic_posts = (
        Post.objects.filter(is_deleted=False)
        .filter(Q(author_id=viewer.pk) | Q(author_id__in=followed_ids))
        .select_related('author', 'reshared_post', 'reshared_post__author')
        .prefetch_related('images')
        .order_by('-created_at', '-pk')
    )
    if cursor_created_at is not None:
        organic_posts = organic_posts.filter(
            Q(created_at__lt=cursor_created_at)
            | Q(created_at=cursor_created_at, pk__lt=cursor_post_id)
        )

    result_window = list(organic_posts[: page_size + 1])
    has_next = len(result_window) > page_size
    posts = result_window[:page_size]
    slot_count = min(max_ads, len(posts) // ad_interval)
    creatives = _eligible_ad_creatives(
        now=timezone.now(),
        campaign_ids=recent_campaign_ids,
        limit=slot_count,
    ) if slot_count else []

    entries = []
    served_campaign_ids = list(recent_campaign_ids)
    next_creative = iter(creatives)
    for organic_index, post in enumerate(posts, start=1):
        entries.append(FeedEntry(post=post))
        if organic_index % ad_interval == 0:
            creative = next(next_creative, None)
            if creative is not None:
                entries.append(FeedEntry(creative=creative))
                served_campaign_ids.append(creative.campaign_id)

    next_cursor = None
    if has_next and posts:
        next_cursor = _encode_cursor(
            viewer_id=viewer.pk,
            post=posts[-1],
            recent_campaign_ids=served_campaign_ids,
        )
    return FeedPage(tuple(entries), next_cursor, has_next)
