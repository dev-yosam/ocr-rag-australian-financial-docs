"""Synthetic/fake parser tests. These do not establish real OCR accuracy."""
from dataclasses import replace

import pytest

from app import cli
from app.core.config import Settings
from app.core.errors import InputError, PipelineError
from app.core.files import read_json, sha256
from app.ocr_pipeline import OcrPipeline
from app.paddleocr.types import ParsedDocument, PartialParseError


def test_ocr_only_without_llm_environment_or_extractors(repo, fake_parser, monkeypatch):
    from app.extraction.invoice import RuleInvoiceExtractor
    from app.llm.adapter import LocalLlmExtractor

    def forbidden(*args, **kwargs):
        raise AssertionError("An extractor must never be constructed")

    monkeypatch.setattr(RuleInvoiceExtractor, "__init__", forbidden)
    monkeypatch.setattr(LocalLlmExtractor, "__init__", forbidden)
    settings = Settings(root=repo, extractor="llm", llm_python="missing/python.exe")
    result = OcrPipeline(settings, fake_parser).parse("invoice.png", "ocr")
    output = repo / "outputs/ocr"
    assert not (repo / ".venv-llm").exists()
    assert set(p.name for p in output.iterdir()) == {"raw.json", "parsed.md", "manifest.json"}
    assert "invoice" not in result and "review" not in result
    assert result["mode"] == "ocr_only" and result["ocr_status"] == "completed"
    assert set(result["artifacts"]) == {"raw.json", "parsed.md", "manifest.json"}
    manifest = read_json(output / "manifest.json")
    assert manifest["schema_version"] == "ocr-run-v1"
    assert manifest["extraction"] == {"strategy": "none", "status": "not_requested"}
    assert manifest["semantic_accuracy_verified"] is False
    assert manifest["status"] == "completed" and manifest["stage"] == "completed"
    assert manifest["source_sha256"] == sha256(repo / "invoice.png")
    assert manifest["versions"] == {"pipeline": "FAKE"}
    assert manifest["elapsed_seconds"] >= 0
    assert set(manifest["artifacts"]) == {"raw.json", "parsed.md"}
    for name, digest in manifest["artifacts"].items():
        assert digest == sha256(output / name)


def test_multiple_pages_raw_preservation_and_markdown_boundary(repo):
    raw = [{"fixture": "FAKE", "res": {"page_index": i, "unknown_provider_field": [1, 2]}}
           for i in range(2)]
    class FakeParser:
        def parse(self, path):
            return ParsedDocument(raw, ["FAKE NO INVOICE FIELDS\r\n1\u00a02", "<table><tr><td>3</td></tr></table>"])
    result = OcrPipeline(Settings(root=repo), FakeParser()).parse("invoice.png", "pages")
    assert result["page_count"] == 2
    assert read_json(repo / "outputs/pages/raw.json") == raw
    assert (repo / "outputs/pages/parsed.md").read_text(encoding="utf-8") == (
        "FAKE NO INVOICE FIELDS\n1 2\n\n<!-- page break -->\n\n<table><tr><td>3</td></tr></table>\n")


@pytest.mark.parametrize("raw,markdown", [([], []), ([{"fixture": "FAKE"}], []),
                                        ([{"fixture": "FAKE"}], ["  \n"]),
                                        ([{}, {}], ["FAKE one page"])])
def test_empty_or_incomplete_results_never_complete(repo, raw, markdown):
    class FakeParser:
        def parse(self, path):
            return ParsedDocument(raw, markdown)
    with pytest.raises(PipelineError):
        OcrPipeline(Settings(root=repo), FakeParser()).parse("invoice.png", "invalid")
    output = repo / "outputs/invalid"
    assert read_json(output / "manifest.json")["ocr_status"] == "failed"
    assert read_json(output / "raw.json") == raw
    assert not (output / "parsed.md").exists()
    assert not (output / "extracted.json").exists()


def test_partial_provider_failure_keeps_raw_and_diagnostics(repo):
    raw = [{"fixture": "FAKE partial page"}]
    diagnostic = {"stage": "parsing", "termination": "timeout", "error_type": "WorkerTimeout",
                  "versions": {"pipeline": "FAKE"}}
    class FakeParser:
        def parse(self, path):
            raise PartialParseError("SECRET provider text", raw, diagnostic)
    with pytest.raises(PipelineError) as error:
        OcrPipeline(Settings(root=repo), FakeParser()).parse("invoice.png", "partial")
    assert "SECRET" not in str(error.value)
    output = repo / "outputs/partial"
    manifest = read_json(output / "manifest.json")
    assert manifest["status"] == manifest["ocr_status"] == "failed"
    assert manifest["failure"] == diagnostic
    assert manifest["versions"] == {"pipeline": "FAKE"}
    assert manifest["artifacts"] == {"raw.json": sha256(output / "raw.json")}
    assert read_json(output / "raw.json") == raw
    assert not (output / "parsed.md").exists()


@pytest.mark.parametrize("failure", [RuntimeError("SECRET"), KeyboardInterrupt()])
def test_unexpected_failure_closes_manifest_without_private_message(repo, failure):
    class FakeParser:
        def parse(self, path):
            raise failure
    with pytest.raises(PipelineError) as error:
        OcrPipeline(Settings(root=repo), FakeParser()).parse("invoice.png", "failed")
    assert "SECRET" not in str(error.value)
    output = repo / "outputs/failed"
    assert set(x.name for x in output.iterdir()) == {"manifest.json"}
    manifest = read_json(output / "manifest.json")
    assert manifest["status"] == "failed"
    assert manifest["failure"]["error_type"] == type(failure).__name__
    assert "SECRET" not in (output / "manifest.json").read_text()


def test_existing_run_not_overwritten(repo, fake_parser):
    service = OcrPipeline(Settings(root=repo), fake_parser)
    service.parse("invoice.png", "same")
    before = sha256(repo / "outputs/same/manifest.json")
    with pytest.raises(InputError):
        service.parse("invoice.png", "same")
    assert sha256(repo / "outputs/same/manifest.json") == before


@pytest.mark.parametrize("source", ["../outside.png", "https://example.com/a.png", "missing.png", "bad.png"])
def test_invalid_source_rejected_before_parser(repo, source):
    (repo / "bad.png").write_bytes(b"not an image")
    class ForbiddenParser:
        def parse(self, path):
            raise AssertionError("Invalid input reached OCR")
    with pytest.raises(InputError):
        OcrPipeline(Settings(root=repo), ForbiddenParser()).parse(source, "invalid")
    assert not (repo / "outputs/invalid").exists()


def test_ocr_env_ignores_all_downstream_settings(monkeypatch):
    for key in ("INVOICE_EXTRACTOR", "LLM_DEVICE", "LLM_PYTHON", "LLM_DTYPE", "LLM_CPU_THREADS",
                "LLM_TIMEOUT_SECONDS", "LLM_MAX_INPUT_TOKENS", "LLM_MAX_NEW_TOKENS", "RAGFLOW_TIMEOUT_SECONDS"):
        monkeypatch.setenv(key, "INVALID_UNUSED_VALUE")
    monkeypatch.setenv("PADDLEOCR_DEVICE", "gpu:0")
    monkeypatch.setenv("PADDLEOCR_TIMEOUT_SECONDS", "600")
    settings = Settings.from_ocr_env()
    assert settings.device == "gpu:0" and settings.ocr_timeout == 600
    assert settings.llm_python == ""


@pytest.mark.parametrize("timeout", ["bad", "0", "3601", "nan", "inf"])
def test_ocr_env_validates_timeout(monkeypatch, timeout):
    monkeypatch.setenv("PADDLEOCR_TIMEOUT_SECONDS", timeout)
    with pytest.raises(InputError):
        Settings.from_ocr_env()


def test_cli_parse_independent_of_invoice_pipeline(repo, fake_parser, monkeypatch, capsys):
    original = Settings.from_ocr_env
    monkeypatch.setenv("INVOICE_EXTRACTOR", "llm")
    monkeypatch.setenv("LLM_CPU_THREADS", "invalid")
    monkeypatch.setattr(Settings, "from_ocr_env", lambda: replace(original(), root=repo))
    def forbidden(*args, **kwargs):
        raise AssertionError("Invoice path must not run")
    monkeypatch.setattr(cli, "InvoicePipeline", forbidden)
    monkeypatch.setattr(Settings, "from_env", forbidden)
    monkeypatch.setattr(cli, "OcrPipeline", lambda settings: OcrPipeline(settings, fake_parser))
    assert cli.main(["parse", "invoice.png", "--run-id", "cli-ocr"]) == 0
    text = capsys.readouterr().out
    assert "OCR 完成" in text and "manifest.json" in text
    assert "Example Synthetic" not in text and "extracted.json" not in text
    assert cli.main(["parse", "invoice.png", "--run-id", "cli-ocr"]) == 1
    assert cli.main(["parse", "../outside.png"]) == 1


def test_ocr_artifacts_can_be_reextracted_without_rerunning_ocr(repo, fake_parser):
    from app.pipeline import InvoicePipeline
    OcrPipeline(Settings(root=repo), fake_parser).parse("invoice.png", "source-ocr")
    original_hash = sha256(repo / "outputs/source-ocr/manifest.json")
    class ForbiddenParser:
        def parse(self, path):
            raise AssertionError("OCR must not run again")
    result = InvoicePipeline(Settings(root=repo), ForbiddenParser()).reextract("outputs/source-ocr", "later-rules")
    assert result["invoice"]["total_cost"] == 1100
    assert sha256(repo / "outputs/source-ocr/manifest.json") == original_hash
    assert not (repo / "outputs/source-ocr/extracted.json").exists()
