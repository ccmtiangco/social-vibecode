from contextlib import suppress

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Post, PostImage


def create_post(*, author, body='', images=(), reshared_post=None):
    body = body or ''
    images = list(images)
    if reshared_post is None and not body.strip() and not images:
        raise ValidationError('An original post needs text or at least one image.')
    if reshared_post is not None and images:
        raise ValidationError('Reshares use the original post images.')

    post = Post(author=author, body=body, reshared_post=reshared_post)
    post.full_clean()
    attachments = [
        PostImage(post=post, image=image, position=position)
        for position, image in enumerate(images)
    ]
    for attachment in attachments:
        attachment.full_clean(exclude=('post',))

    stored_files = []
    try:
        with transaction.atomic():
            post.save()
            for attachment in attachments:
                attachment.post = post
                attachment.image.save(
                    attachment.image.name,
                    attachment.image.file,
                    save=False,
                )
                stored_files.append((attachment.image.storage, attachment.image.name))
                attachment.save()
    except Exception:
        for storage, name in stored_files:
            with suppress(OSError):
                storage.delete(name)
        raise

    return post
