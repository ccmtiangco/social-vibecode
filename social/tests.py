from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from PIL import Image

from accounts.models import User
from .models import Follow, Post, PostImage
from .services import create_post


class FollowConstraintTests(TestCase):
    def setUp(self):
        self.follower = User.objects.create_user(username='follower')
        self.followed = User.objects.create_user(username='followed')

    def test_follow_relationship_is_unique(self):
        Follow.objects.create(follower=self.follower, followed=self.followed)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Follow.objects.create(follower=self.follower, followed=self.followed)

    def test_user_cannot_follow_themself(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Follow.objects.create(follower=self.follower, followed=self.follower)


class PostCreationTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(username='author')
        self.sharer = User.objects.create_user(username='sharer')

    def test_original_post_requires_text_or_an_image(self):
        with self.assertRaises(ValidationError):
            create_post(author=self.author)

    def test_text_post_is_created(self):
        post = create_post(author=self.author, body='Hello, social site.')

        self.assertEqual(post.author, self.author)
        self.assertEqual(post.body, 'Hello, social site.')
        self.assertIsNone(post.reshared_post)

    def test_reshare_references_original_instead_of_copying_its_body(self):
        original = create_post(author=self.author, body='Original content')

        reshare = create_post(
            author=self.sharer,
            reshared_post=original,
            body='My comment',
        )

        self.assertEqual(reshare.reshared_post, original)
        self.assertEqual(reshare.body, 'My comment')
        self.assertNotEqual(reshare.body, original.body)

    def test_reshare_must_point_to_an_original_post(self):
        original = create_post(author=self.author, body='Original content')
        first_reshare = create_post(author=self.sharer, reshared_post=original)

        with self.assertRaises(ValidationError):
            create_post(author=self.author, reshared_post=first_reshare)

    def test_database_rejects_a_post_resharing_itself(self):
        post = create_post(author=self.author, body='Original content')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Post.objects.filter(pk=post.pk).update(reshared_post=post)


class PostImageTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(username='image-author')
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        media_settings = override_settings(MEDIA_ROOT=self.media_directory.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)

    def image_upload(self, name='photo.png'):
        output = BytesIO()
        Image.new('RGB', (8, 8), color='red').save(output, format='PNG')
        return SimpleUploadedFile(name, output.getvalue(), content_type='image/png')

    def test_image_only_post_is_saved_with_multiple_ordered_images(self):
        post = create_post(
            author=self.author,
            images=[self.image_upload('first.png'), self.image_upload('second.png')],
        )

        images = list(post.images.order_by('position'))
        self.assertEqual(len(images), 2)
        self.assertEqual([image.position for image in images], [0, 1])
        self.assertNotIn('first.png', images[0].image.name)
        self.assertTrue(Path(self.media_directory.name, images[0].image.name).is_file())

    def test_non_image_upload_is_rejected(self):
        bad_image = SimpleUploadedFile(
            'not-an-image.png',
            b'this is not image data',
            content_type='image/png',
        )

        with self.assertRaises(ValidationError):
            create_post(author=self.author, images=[bad_image])

        self.assertEqual(Post.objects.count(), 0)

    def test_oversized_upload_is_rejected(self):
        oversized_image = SimpleUploadedFile(
            'large.png',
            b'x' * (5 * 1024 * 1024 + 1),
            content_type='image/png',
        )

        with self.assertRaises(ValidationError):
            create_post(author=self.author, images=[oversized_image])

        self.assertEqual(Post.objects.count(), 0)

    def test_invalid_image_does_not_leave_a_partial_post_or_uploaded_file(self):
        valid_image = self.image_upload()
        invalid_image = SimpleUploadedFile('broken.png', b'invalid')

        with self.assertRaises(ValidationError):
            create_post(author=self.author, images=[valid_image, invalid_image])

        self.assertEqual(Post.objects.count(), 0)
        stored_files = [
            path
            for path in Path(self.media_directory.name).rglob('*')
            if path.is_file()
        ]
        self.assertEqual(stored_files, [])

    def test_deleting_reshared_post_tombstones_original_and_removes_media(self):
        original = create_post(
            author=self.author,
            body='Content to remove',
            images=[self.image_upload()],
        )
        reshare = create_post(
            author=User.objects.create_user(username='tombstone-sharer'),
            reshared_post=original,
        )
        image = original.images.get()
        image_path = Path(self.media_directory.name, image.image.name)

        with self.captureOnCommitCallbacks(execute=True):
            original.delete()

        original.refresh_from_db()
        reshare.refresh_from_db()
        self.assertTrue(original.is_deleted)
        self.assertIsNotNone(original.deleted_at)
        self.assertEqual(original.body, '')
        self.assertTrue(reshare.reshared_post.is_deleted)
        self.assertFalse(original.images.exists())
        self.assertFalse(image_path.exists())

    def test_deleting_unshared_post_removes_its_image_file(self):
        post = create_post(author=self.author, images=[self.image_upload()])
        image_path = Path(self.media_directory.name, post.images.get().image.name)

        with self.captureOnCommitCallbacks(execute=True):
            post.delete()

        self.assertFalse(Post.objects.filter(pk=post.pk).exists())
        self.assertFalse(image_path.exists())
