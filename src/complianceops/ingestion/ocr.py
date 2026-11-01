"""Text extraction from images with Tesseract."""

import io

import pytesseract
from PIL import Image, UnidentifiedImageError

OCR_LANGUAGES = "fra+eng"


class OcrUnavailableError(RuntimeError):
    """Tesseract is needed but not installed.

    This is an error rather than a skipped block: silently losing text could hide a violation.
    """


def ocr_image(image_bytes: bytes) -> str:
    """Return the text in an image, or an empty string if the format cannot be decoded."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except (UnidentifiedImageError, OSError):
        return ""
    try:
        return str(pytesseract.image_to_string(image, lang=OCR_LANGUAGES)).strip()
    except pytesseract.TesseractNotFoundError as error:
        raise OcrUnavailableError(
            "Tesseract is required to read images in this document but is not installed."
        ) from error
