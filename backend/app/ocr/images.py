"""Phone photos and image scans (E2-08/E2-14): normalise to a one-page PDF.

The rest of the pipeline — OCR, bounding boxes, the lineage viewer — works in PDF points,
so a JPEG/PNG is turned upright using its EXIF orientation (phones store most photos
sideways and set a flag instead of rotating the pixels) and placed on a page of
width = pixels x 72 / IMAGE_DPI. The original bytes are what is fingerprinted and kept.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

IMAGE_DPI = 150
MAX_PIXELS = 40_000_000

IMAGE_MIME = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG\r\n\x1a\n": "image/png"}


def sniff_image(data: bytes) -> str | None:
    return next((mime for magic, mime in IMAGE_MIME.items() if data.startswith(magic)), None)


class BadImage(ValueError):
    pass


def upright(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > MAX_PIXELS:
            raise BadImage("image is too large")
        img = ImageOps.exif_transpose(img)
        return img.convert("RGB") if img.mode not in ("RGB", "L") else img
    except (UnidentifiedImageError, OSError) as e:
        raise BadImage(f"unreadable image: {e}") from e


def page_size(img: Image.Image) -> tuple[float, float]:
    return img.width * 72 / IMAGE_DPI, img.height * 72 / IMAGE_DPI


def image_to_pdf(data: bytes) -> bytes:
    img = upright(data)
    w, h = page_size(img)
    buf, jpg = io.BytesIO(), io.BytesIO()
    img.save(jpg, "JPEG", quality=90)
    c = Canvas(buf, pagesize=(w, h), invariant=1)
    c.drawImage(ImageReader(io.BytesIO(jpg.getvalue())), 0, 0, width=w, height=h)
    c.showPage()
    c.save()
    return buf.getvalue()
