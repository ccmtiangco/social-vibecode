from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class UserType(models.TextChoices):
        MEMBER = 'member', 'Member'
        AD_MANAGER = 'ad_manager', 'Ad manager'

    user_type = models.CharField(
        max_length=20,
        choices=UserType.choices,
        default=UserType.MEMBER,
    )
