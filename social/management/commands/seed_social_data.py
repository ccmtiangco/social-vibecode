from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from PIL import Image

from accounts.models import User
from social.models import Follow, Post
from social.services import create_post


class Command(BaseCommand):
    help = 'Create repeatable sample members, follows, posts, and reshares for development.'

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('seed_social_data is only available when DEBUG=True.')

        ava = self.get_member('demo_ava', 'ava@example.test')
        ben = self.get_member('demo_ben', 'ben@example.test')
        casey = self.get_member('demo_casey', 'casey@example.test')

        Follow.objects.get_or_create(follower=ava, followed=ben)
        Follow.objects.get_or_create(follower=ben, followed=casey)
        Follow.objects.get_or_create(follower=casey, followed=ava)

        ava_post = self.get_original_post(ava, 'Welcome to the demo social site.')
        self.get_original_post(
            ben,
            'A sample post with an image.',
            images=[self.demo_image()],
        )
        self.get_reshare(casey, ava_post)

        self.stdout.write(self.style.SUCCESS('Development social data is ready.'))

    def get_member(self, username, email):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': email,
                'user_type': User.UserType.MEMBER,
            },
        )
        if user.user_type != User.UserType.MEMBER:
            raise CommandError(f'{username} exists but is not a member account.')
        if created:
            user.set_unusable_password()
            user.save(update_fields=('password',))
        return user

    def get_original_post(self, author, body, images=()):
        existing = Post.objects.filter(
            author=author,
            body=body,
            reshared_post__isnull=True,
            is_deleted=False,
        ).first()
        if existing:
            return existing
        return create_post(author=author, body=body, images=images)

    def get_reshare(self, author, original):
        existing = Post.objects.filter(
            author=author,
            reshared_post=original,
            body='',
            is_deleted=False,
        ).first()
        if existing:
            return existing
        return create_post(author=author, reshared_post=original)

    @staticmethod
    def demo_image():
        output = BytesIO()
        Image.new('RGB', (320, 180), color='#dce9e4').save(output, format='PNG')
        return ContentFile(output.getvalue(), name='demo.png')
