"""Input signature tests; no real documents or OCR."""
import pytest

from app.core.documents import check_document
from app.core.errors import InputError


@pytest.mark.parametrize("prefix", [b"", b"\r\n", b" \t\r\n", b" " * 16])
def test_pdf_with_small_whitespace_prefix_is_accepted_unchanged(tmp_path, prefix):
    path = tmp_path / "synthetic.pdf"
    contents = prefix + b"%PDF-1.4\nsynthetic"
    path.write_bytes(contents)
    check_document(path)
    assert path.read_bytes() == contents


@pytest.mark.parametrize("contents", [b" " * 17 + b"%PDF-1.4", b"junk%PDF-1.4", b"\n<html>%PDF-1.4", b"\r\nnot PDF"])
def test_arbitrary_prefix_or_excess_whitespace_is_rejected(tmp_path, contents):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(contents)
    with pytest.raises(InputError, match="Invalid PDF signature"):
        check_document(path)
