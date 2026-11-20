"""Upload validation. Extensions are not trusted: content is sniffed."""
import re

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

LOGO_MAX = 2 * 1024 * 1024
DOC_MAX = 5 * 1024 * 1024
IMAGE_MAX = 5 * 1024 * 1024
RISKY_SVG = re.compile(rb'<\s*script|\bon[a-z]+\s*=|javascript:|<\s*foreignObject|<!ENTITY|xlink:href\s*=\s*["\']\s*(?!#)', re.I)


def _read(f, limit):
    if f.size > limit:
        raise ValidationError(f'File is too large (max {limit // (1024 * 1024)} MB).')
    f.seek(0)
    data = f.read(limit + 1)
    f.seek(0)
    return data


def _is_real_image(f, allowed):
    try:
        f.seek(0)
        img = Image.open(f)
        fmt = (img.format or '').upper()
        img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        return False
    finally:
        f.seek(0)
    return fmt in allowed


def validate_logo(f):
    """PNG, JPG or SVG, max 2 MB."""
    data = _read(f, LOGO_MAX)
    if data.lstrip()[:5].lower() in (b'<?xml', b'<svg ') or b'<svg' in data[:1024].lower():
        if RISKY_SVG.search(data):
            raise ValidationError('This SVG contains scripts or external references. Export a plain SVG, or use PNG/JPG.')
        return f
    if not _is_real_image(f, {'PNG', 'JPEG'}):
        raise ValidationError('Upload a PNG, JPG or SVG image.')
    return f


def validate_document(f):
    """Photo (JPG/PNG) or PDF, max 5 MB."""
    data = _read(f, DOC_MAX)
    if data[:5] == b'%PDF-':
        return f
    if not _is_real_image(f, {'PNG', 'JPEG'}):
        raise ValidationError('Upload a photo (JPG/PNG) or a PDF.')
    return f


def validate_product_image(f):
    """JPG or PNG, max 5 MB."""
    _read(f, IMAGE_MAX)
    if not _is_real_image(f, {'PNG', 'JPEG', 'WEBP'}):
        raise ValidationError('Upload a JPG, PNG or WebP image.')
    return f
