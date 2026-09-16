import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.errors import InputError, PipelineError
from app.core.files import contained, read_json
from app.paddleocr.normalize import normalize_markdown
from app.paddleocr.types import PartialParseError
from app.pipeline import InvoicePipeline
from app.rag.artifacts import prepare


def test_artifacts_and_offline_preparation(repo, fake_parser):
    result = InvoicePipeline(Settings(root=repo), fake_parser).process("invoice.png", "sample")
    output = repo / "outputs/sample"
    assert result["invoice"]["total_cost"] == 1100
    assert len(result["invoice"]) == 14
    assert read_json(output / "raw.json")[0]["fixture"] == "FAKE"
    assert read_json(output / "manifest.json")["status"] == "completed"
    receipt = prepare(repo, "outputs/sample")
    assert receipt["status"] == "prepared"
    assert prepare(repo, "outputs/sample") == receipt
    (output / "parsed.md").write_text("changed")
    with pytest.raises(InputError):
        prepare(repo, "outputs/sample")


def test_no_overwriting_existing_run(repo, fake_parser):
    service = InvoicePipeline(Settings(root=repo), fake_parser)
    service.process("invoice.png", "same")
    with pytest.raises(InputError):
        service.process("invoice.png", "same")


def test_partial_raw_retained(repo):
    class Failing:
        def parse(self, path):
            raise PartialParseError("provider failed", [{"page": 1}])
    with pytest.raises(PipelineError):
        InvoicePipeline(Settings(root=repo), Failing()).process("invoice.png", "failed")
    output = repo / "outputs/failed"
    assert read_json(output / "raw.json") == [{"page": 1}]
    assert not (output / "extracted.json").exists()
    assert read_json(output / "manifest.json")["status"] == "failed"


@pytest.mark.parametrize("path", ["../outside", "C:/private.txt", "https://example.com/a", "outputs/../../x", "x:stream"])
def test_path_boundary(repo, path):
    with pytest.raises(InputError):
        contained(repo, path, must_exist=False)


def test_symlink_escape(repo):
    link = repo / "escape"
    try:
        link.symlink_to(repo.parent, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit symlink creation")
    with pytest.raises(InputError):
        contained(repo, "escape", must_exist=False)


def test_invalid_image(repo, fake_parser):
    (repo / "broken.png").write_bytes(b"broken")
    with pytest.raises(InputError):
        InvoicePipeline(Settings(root=repo), fake_parser).process("broken.png")


def test_markdown_structure():
    assert normalize_markdown(["A\r\n| 1\u00a02 | 3 |  \r\n", "next"]) == "A\n| 1 2 | 3 |  \n\n<!-- page break -->\n\nnext\n"


def test_api_does_not_leak_request_or_document(repo, fake_parser, caplog):
    with TestClient(create_app(InvoicePipeline(Settings(root=repo), fake_parser))) as client:
        assert client.get("/health").json()["ocr_readiness"] == "not_checked"
        response = client.post("/v1/invoices/process", json={"source": "invoice.png"})
        assert response.status_code == 200
        assert response.json()["invoice"]["total_cost"] == 1100
        assert len(response.json()["invoice"]) == 14
        assert '"total_cost": 1100.00' in response.text
        bad = client.post("/v1/invoices/process", json={"source": {"secret": "PRIVATE"}})
        assert bad.status_code == 422
        assert "PRIVATE" not in bad.text
        assert "Example Synthetic Services" not in caplog.text
        assert client.post("/v1/invoices/process", json={"source": "../private"}).status_code == 400
