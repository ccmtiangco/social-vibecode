from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from .validators import validate_post_image


class Post(models.Model):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='authored_posts',
        db_index=False,
    )
    body = models.TextField(blank=True, default='')
    reshared_post = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        related_name='reshares',
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(reshared_post__isnull=True) | ~Q(pk=F('reshared_post')),
                name='social_post_not_reshare_self',
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_deleted=False, deleted_at__isnull=True)
                    | Q(is_deleted=True, deleted_at__isnull=False)
                ),
                name='social_post_deleted_timestamp_consistent',
            ),
        ]
        indexes = [
            models.Index(
                fields=('author', '-created_at', '-id'),
                name='social_post_author_feed_idx',
            ),
        ]

    def clean(self):
        super().clean()
        if self.reshared_post_id is None:
            return
        if self.pk == self.reshared_post_id:
            raise ValidationError({'reshared_post': 'A post cannot reshare itself.'})
        if self.reshared_post.reshared_post_id is not None:
            raise ValidationError(
                {'reshared_post': 'A reshare must reference an original post.'}
            )
        if self.reshared_post.is_deleted:
            raise ValidationError(
                {'reshared_post': 'A deleted post cannot be reshared.'}
            )

    def delete(self, using=None, keep_parents=False):
        if self.is_deleted:
            return 0, {}
        if self.reshares.exists():
            self.body = ''
            self.is_deleted = True
            self.deleted_at = timezone.now()
            self.save(update_fields=('body', 'is_deleted', 'deleted_at'))
            self.images.all().delete()
            return 0, {}
        return super().delete(using=using, keep_parents=keep_parents)

    def __str__(self):
        if self.reshared_post_id:
            return f'{self.author} reshared post {self.reshared_post_id}'
        return f'Post {self.pk} by {self.author}'


def post_image_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    return f'posts/{instance.post_id}/{uuid4().hex}{extension}'


class PostImage(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(
        upload_to=post_image_upload_to,
        validators=[validate_post_image],
    )
    position = models.PositiveIntegerField(validators=[MinValueValidator(0)])
    alt_text = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('post', 'position'),
                name='social_post_image_position_unique',
            ),
        ]
        ordering = ('position', 'id')

    def __str__(self):
        return f'Image {self.position} on post {self.post_id}'


class Follow(models.Model):
    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='outgoing_follows',
        db_index=False,
    )
    followed = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='incoming_follows',
        db_index=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('follower', 'followed'),
                name='social_follow_unique_pair',
            ),
            models.CheckConstraint(
                condition=~Q(follower=F('followed')),
                name='social_follow_no_self_follow',
            ),
        ]
        indexes = [
            models.Index(
                fields=('followed', 'follower'),
                name='social_follow_reverse_idx',
            ),
        ]

    def __str__(self):
        return f'{self.follower} follows {self.followed}'
