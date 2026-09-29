from pathlib import Path

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError


MAX_POST_IMAGE_SIZE = 5 * 1024 * 1024
MAX_POST_IMAGE_PIXELS = 40_000_000
IMAGE_EXTENSIONS = {
    'JPEG': {'.jpg', '.jpeg'},
    'PNG': {'.png'},
    'WEBP': {'.webp'},
}


def validate_post_image(upload):
    if upload.size > MAX_POST_IMAGE_SIZE:
        raise ValidationError('Images must be 5 MB or smaller.')

    try:
        with Image.open(upload) as image:
            image_format = image.format
            if image.width * image.height > MAX_POST_IMAGE_PIXELS:
                raise ValidationError('Image dimensions are too large.')
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError('Upload a valid JPEG, PNG, or WebP image.') from None
    finally:
        upload.seek(0)

    extension = Path(upload.name).suffix.lower()
    if extension not in IMAGE_EXTENSIONS.get(image_format, set()):
        raise ValidationError('The image extension must match its actual image format.')
