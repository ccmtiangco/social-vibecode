from functools import partial

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import PostImage


@receiver(post_delete, sender=PostImage, dispatch_uid='social.delete_post_image_file')
def delete_post_image_file(sender, instance, using, **kwargs):
    if instance.image:
        transaction.on_commit(
            partial(instance.image.storage.delete, instance.image.name),
            using=using,
        )
