"""Shared input validation for document parsing and invoice extraction."""
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.core.errors import InputError


def check_document(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0 or path.stat().st_size > 20 * 1024 * 1024:
        raise InputError("Document must be a nonempty file of at most 20 MiB")
    if path.suffix.lower() == ".pdf":
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise InputError("Invalid PDF signature")
    elif path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        try:
            with Image.open(path) as image:
                if image.width * image.height > 25_000_000:
                    raise InputError("Image exceeds 25 megapixels")
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise InputError("Invalid image") from None
    else:
        raise InputError("Supported formats: PDF, PNG, JPEG")
