"""Synthetic/fake worker tests; never evidence of real Qwen accuracy."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import cli
from app.api.main import create_app
from app.core.config import Settings
from app.core.errors import ExtractionError, InputError, PipelineError
from app.core.files import read_json, sha256, write_json
from app.llm import adapter
from app.llm.adapter import LocalLlmExtractor
from app.paddleocr.adapter import WorkerOutcome
from app.pipeline import InvoicePipeline
from app.schemas.invoice import TaxInvoice


@pytest.fixture
def fake_llm(repo, monkeypatch):
    python = repo / "fake-python.exe"
    python.write_text("FAKE EXECUTABLE; never invoked")
    settings = Settings(root=repo, extractor="llm", llm_python="fake-python.exe")
    values = TaxInvoice().model_dump(mode="python")
    values.update(total_cost=1100, seller_business_name="Example Synthetic Services")
    evidence = {key: [] for key in values}
    evidence.update(total_cost=["1,100.00"], seller_business_name=["Example Synthetic Services"])
    text = json.dumps({"invoice": values, "evidence": evidence})

    def execute(command, root, timeout):
        assert command[1:3] == ["-m", "app.llm.worker"]
        request = read_json(root / command[3])
        assert request["device"] == settings.llm_device
        assert request["messages"][1]["role"] == "user"
        write_json(root / command[4], {"status": "completed", "text": text,
                                     "model": {"fixture": "FAKE"}})
        return WorkerOutcome(0, "exited", 0.01)
    monkeypatch.setattr(adapter, "execute_worker", execute)
    return settings


def test_real_adapter_fake_worker_pipeline_and_api(repo, fake_parser, fake_llm):
    service = InvoicePipeline(fake_llm, fake_parser)
    result = service.process("invoice.png", "llm")
    assert result["invoice"]["total_cost"] == 1100
    assert result["invoice"]["is_total_cost_equal_to_or_higher_than_1000"] is True
    assert set(result["artifacts"]) == {"raw.json", "parsed.md", "llm_request.json", "llm_response.json", "review.json", "extracted.json"}
    assert result["status"] == "completed" and result["requires_review"] is False
    output = repo / "outputs/llm"
    manifest = read_json(output / "manifest.json")
    assert manifest["extraction"]["strategy"] == "llm"
    for name, digest in manifest["artifacts"].items():
        assert digest == sha256(output / name)
    assert read_json(output / "llm_response.json")["validation"] == "passed"
    assert read_json(output / "review.json")["semantic_accuracy_verified"] is False
    with TestClient(create_app(service)) as client:
        assert client.get("/health").json()["extractor"] == "llm"
        response = client.post("/v1/invoices/process", json={"source": "invoice.png"})
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        assert response.json()["requires_review"] is False
        assert len(response.json()["invoice"]) == 15
        assert isinstance(response.json()["invoice"]["total_cost"], (int, float))


@pytest.fixture
def fake_review_llm(fake_llm, monkeypatch):
    """A fake response with plausible categories but invented source quotations."""
    original = adapter.execute_worker

    def execute(command, root, timeout):
        outcome = original(command, root, timeout)
        path = root / command[4]
        payload = read_json(path)
        response = json.loads(payload["text"])
        response["invoice"].update(supply_type="goods", expense_category="food", taxable_sale_extent=100)
        response["evidence"].update(supply_type=["goods"], expense_category=["food"],
                                    taxable_sale_extent=["SYNTHETIC UNSUPPORTED TAX CLAIM"])
        payload["text"] = json.dumps(response)
        write_json(path, payload)
        return outcome

    monkeypatch.setattr(adapter, "execute_worker", execute)
    return fake_llm


def test_review_retains_values_and_hashes_without_claiming_accuracy(repo, fake_parser, fake_review_llm):
    result = InvoicePipeline(fake_review_llm, fake_parser).process("invoice.png", "review")
    output = repo / "outputs/review"
    assert result["status"] == "completed_needs_review"
    assert result["requires_review"] is True
    assert result["invoice"]["supply_type"] == "goods"
    assert result["invoice"]["expense_category"] == "food"
    assert result["invoice"]["taxable_sale_extent"] == 100
    assert result["invoice"]["date_of_expense"] is None
    assert result["invoice"]["is_total_cost_equal_to_or_higher_than_1000"] is True
    invoice = read_json(output / "extracted.json")
    assert len(invoice) == 15 and invoice["total_cost"] == 1100
    manifest = read_json(output / "manifest.json")
    assert manifest["status"] == "completed_needs_review"
    review = read_json(output / "review.json")
    assert set(review["fields"]) == set(invoice)
    assert review["semantic_accuracy_verified"] is False
    assert "date_of_expense" in review["missing_fields"]
    assert {issue["field"] for issue in review["issues"]} == {"supply_type", "expense_category", "taxable_sale_extent"}
    assert set(result["review"]["fields_requiring_review"]) == {"supply_type", "expense_category", "taxable_sale_extent"}
    response = read_json(output / "llm_response.json")
    assert response["validation"] == "passed_with_review"
    assert response["format_validation"] == "passed"
    assert response["review_sha256"] == sha256(output / "review.json")
    assert json.loads(response["text"])["evidence"]["expense_category"] == ["food"]
    for name, digest in manifest["artifacts"].items():
        assert digest == sha256(output / name)


def test_api_exposes_review_status_instead_of_service_failure(repo, fake_parser, fake_review_llm):
    with TestClient(create_app(InvoicePipeline(fake_review_llm, fake_parser))) as client:
        response = client.post("/v1/invoices/process", json={"source": "invoice.png"})
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "completed_needs_review" and result["requires_review"] is True
    assert "expense_category" in result["review"]["fields_requiring_review"]
    assert result["artifacts"]["review.json"].endswith("/review.json")
    assert result["invoice"]["expense_category"] == "food"


def test_uncertain_total_also_marks_derived_flag_in_summary(repo, fake_parser, fake_llm, monkeypatch):
    original = adapter.execute_worker

    def execute(command, root, timeout):
        outcome = original(command, root, timeout)
        path = root / command[4]
        payload = read_json(path)
        response = json.loads(payload["text"])
        response["evidence"]["total_cost"] = []
        payload["text"] = json.dumps(response)
        write_json(path, payload)
        return outcome

    monkeypatch.setattr(adapter, "execute_worker", execute)
    result = InvoicePipeline(fake_llm, fake_parser).process("invoice.png", "uncertain-total")
    assert result["requires_review"] is True
    assert set(result["review"]["fields_requiring_review"]) == {"total_cost", "is_total_cost_equal_to_or_higher_than_1000"}
    assert result["invoice"]["total_cost"] == 1100
    assert result["invoice"]["is_total_cost_equal_to_or_higher_than_1000"] is True


def test_cli_replay_surfaces_review_without_logging_receipt(repo, fake_parser, fake_review_llm, monkeypatch, capsys):
    InvoicePipeline(Settings(root=repo), fake_parser).process("invoice.png", "original")
    original = repo / "outputs/original/manifest.json"
    digest = sha256(original)
    monkeypatch.setattr(cli.Settings, "from_env", lambda: fake_review_llm)
    assert cli.main(["extract", "outputs/original", "--extractor", "llm", "--run-id", "needs-review"]) == 0
    text = capsys.readouterr().out
    assert "completed_needs_review" in text
    assert "需要人工確認" in text and "expense_category" in text
    assert "outputs/needs-review/review.json" in text
    assert "Example Synthetic" not in text and "SYNTHETIC UNSUPPORTED" not in text
    assert sha256(original) == digest
    output = repo / "outputs/needs-review"
    assert read_json(output / "manifest.json")["status"] == "completed_needs_review"
    assert (output / "extracted.json").exists()


@pytest.mark.parametrize("field,value", [("date_of_issue", "2026-02-30"), ("total_cost", "1100.00")])
def test_invalid_values_still_fail_without_extracted_json(repo, fake_parser, fake_llm, monkeypatch, field, value):
    original = adapter.execute_worker

    def execute(command, root, timeout):
        outcome = original(command, root, timeout)
        path = root / command[4]
        payload = read_json(path)
        response = json.loads(payload["text"])
        response["invoice"][field] = value
        payload["text"] = json.dumps(response)
        write_json(path, payload)
        return outcome

    monkeypatch.setattr(adapter, "execute_worker", execute)
    with pytest.raises(PipelineError):
        InvoicePipeline(fake_llm, fake_parser).process("invoice.png", "invalid")
    output = repo / "outputs/invalid"
    assert read_json(output / "manifest.json")["status"] == "failed"
    assert (output / "llm_response.json").exists() and (output / "raw.json").exists()
    assert not (output / "extracted.json").exists()


@pytest.mark.parametrize("failure", ["timeout", "invalid_json", "invalid_payload", "exit", "missing_result"])
def test_failure_retains_ocr_and_response_without_success(repo, fake_parser, fake_llm, monkeypatch, failure):
    def execute(command, root, timeout):
        if failure != "missing_result":
            write_json(root / command[4], [] if failure == "invalid_payload" else
                       {"status": "completed", "text": "PRIVATE_DOCUMENT_INVALID_JSON"})
        return WorkerOutcome(1 if failure == "exit" else 0, "timeout" if failure == "timeout" else "exited", 0.01)
    monkeypatch.setattr(adapter, "execute_worker", execute)
    with pytest.raises(PipelineError) as error:
        InvoicePipeline(fake_llm, fake_parser).process("invoice.png", failure)
    assert "PRIVATE" not in str(error.value)
    output = repo / f"outputs/{failure}"
    assert (output / "raw.json").exists() and (output / "parsed.md").exists()
    assert (output / "llm_response.json").exists()
    assert not (output / "extracted.json").exists()
    assert read_json(output / "manifest.json")["status"] == "failed"
    if failure == "invalid_json":
        response = read_json(output / "llm_response.json")
        assert response["status"] == "failed" and response["stage"] == "validation"
        assert response["generation_status"] == "completed"


def test_replay_skips_parser_and_preserves_prior_run(repo, fake_parser, fake_llm):
    InvoicePipeline(Settings(root=repo), fake_parser).process("invoice.png", "original")
    original = repo / "outputs/original/manifest.json"
    digest = sha256(original)
    class Forbidden:
        def parse(self, path):
            pytest.fail("Replay must not rerun OCR")
    result = InvoicePipeline(fake_llm, Forbidden()).reextract("outputs/original", "replayed")
    assert result["invoice"]["seller_business_name"] == "Example Synthetic Services"
    assert sha256(original) == digest
    assert read_json(repo / "outputs/replayed/manifest.json")["replayed_from"]["manifest_sha256"] == digest


@pytest.mark.parametrize("artifact", ["parsed.md", "raw.json"])
def test_replay_rejects_tampered_ocr(repo, fake_parser, artifact):
    service = InvoicePipeline(Settings(root=repo), fake_parser)
    service.process("invoice.png", "original")
    (repo / "outputs/original" / artifact).write_text("FAKE TAMPERING")
    with pytest.raises(InputError):
        service.reextract("outputs/original", "rejected")
    assert not (repo / "outputs/rejected").exists()


@pytest.mark.parametrize("key,value", [("source_sha256", None), ("source_sha256", "bad"), ("versions", [])])
def test_replay_requires_provenance(repo, fake_parser, key, value):
    service = InvoicePipeline(Settings(root=repo), fake_parser)
    service.process("invoice.png", "original")
    path = repo / "outputs/original/manifest.json"
    manifest = read_json(path)
    manifest[key] = value
    write_json(path, manifest)
    with pytest.raises(InputError):
        service.reextract("outputs/original", "rejected")
    assert not (repo / "outputs/rejected").exists()


def test_replay_rules_baseline_and_cli(repo, fake_parser, monkeypatch, capsys):
    service = InvoicePipeline(Settings(root=repo), fake_parser)
    service.process("invoice.png", "original")
    monkeypatch.setattr(cli.Settings, "from_env", lambda: Settings(root=repo))
    assert cli.main(["extract", "outputs/original", "--extractor", "rules", "--run-id", "replay"]) == 0
    assert "Example Synthetic" not in capsys.readouterr().out
    assert cli.main(["extract", "outputs/original", "--run-id", "replay"]) == 1


def test_missing_llm_does_not_fall_back(repo, fake_parser):
    with pytest.raises(PipelineError):
        InvoicePipeline(Settings(root=repo, extractor="llm"), fake_parser).process("invoice.png", "missing")
    assert not (repo / "outputs/missing/extracted.json").exists()


@pytest.mark.parametrize("key,value", [("extractor", "cloud"), ("llm_device", "auto"), ("llm_timeout", float("nan")),
    ("llm_timeout", 0), ("llm_max_input_tokens", 20000), ("llm_max_new_tokens", 0), ("llm_threads", 0), ("llm_dtype", "int4")])
def test_config_rejects_invalid(key, value):
    with pytest.raises(InputError):
        Settings(**{key: value})


def test_environment_configuration(monkeypatch):
    monkeypatch.setenv("PADDLEOCR_DEVICE", "gpu:0")
    monkeypatch.setenv("INVOICE_EXTRACTOR", "llm")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "3600")
    monkeypatch.delenv("LLM_DEVICE", raising=False)
    settings = Settings.from_env()
    assert settings.llm_device == "gpu:0" and settings.llm_timeout == 3600
    monkeypatch.setenv("LLM_DEVICE", "cpu")
    assert Settings.from_env().llm_device == "cpu"
    monkeypatch.setenv("LLM_CPU_THREADS", "oops")
    with pytest.raises(InputError):
        Settings.from_env()
