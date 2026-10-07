"""Synthetic fixtures + fake HTTP only; no evidence of live Gemini accuracy."""
from decimal import Decimal
import json

import httpx
import pytest

from app import cli
from app.core.errors import InputError, PipelineError
from app.core.files import json_text, read_json, sha256, write_json
from app.gemini.client import GeminiClient, GeminiError
from app.gemini.config import ENDPOINT, MODEL, GeminiSettings
from app.gemini.contract import FIELDS, THRESHOLD, assess, build_request, ocr_blocks, response_schema
from app.gemini.pipeline import GeminiPipeline
from app.schemas.invoice import TaxInvoice

KEY = "FAKE-KEY-NOT-A-REAL-CREDENTIAL"
RAW = [{"res": {"input_path": "/private/do-not-send.png", "parsing_res_list": [
    {"block_id": 9, "block_label": "header", "block_content": "SYNTHETIC EXAMPLE ABN 12345678901",
     "block_bbox": [0, 0, 100, 50], "block_order": None, "unrelated": "DO-NOT-SEND"},
    {"block_id": 2, "block_label": "table", "block_content": "<table><tr><td>Total</td><td>1100.00</td></tr></table>",
     "block_bbox": [0, 50, 100, 100], "block_order": 0},
    {"block_id": 3, "block_label": "footer", "block_content": "SYNTHETIC THANK YOU", "block_order": 1},
]}}]


def answer():
    invoice = TaxInvoice().model_dump(mode="python")
    invoice.update(total_cost=Decimal("1100.00"), seller_abn="12345678901")
    # Deliberately wrong derived value: Python must retain it, flag it, never fix it.
    invoice[THRESHOLD] = False
    evidence = {field: [] for field in FIELDS}
    evidence["total_cost"] = [{"block_ref": "p1:b1", "quote": "1100.00"}]
    evidence[THRESHOLD] = evidence["total_cost"]
    evidence["seller_abn"] = [{"block_ref": "p1:b0", "quote": "ABN 12345678901"}]
    return {"invoice": invoice, "evidence": evidence, "currency": "AUD"}


def response(text=None):
    return {"modelVersion": MODEL, "usageMetadata": {"totalTokenCount": 222}, "candidates": [
        {"finishReason": "STOP", "content": {"parts": [{"text": text or json_text(answer())}]}}
    ]}


@pytest.fixture
def saved(repo):
    output = repo / "outputs/original"
    output.mkdir(parents=True)
    write_json(output / "raw.json", RAW)
    (output / "parsed.md").write_text("FAKE MARKDOWN WITHOUT HEADER", encoding="utf-8")
    write_json(output / "manifest.json", {
        "run_id": "renamed-original-folder", "status": "completed", "ocr_status": "completed",
        "source": "invoice.png", "source_sha256": sha256(repo / "invoice.png"), "versions": {"fixture": "FAKE"},
        "artifacts": {name: sha256(output / name) for name in ("raw.json", "parsed.md")},
    })
    return repo


def fake_client(payload=None, handler=None):
    def default(request):
        return httpx.Response(200, content=json_text(payload if payload is not None else response()).encode())
    return GeminiClient(GeminiSettings(api_key=KEY), transport=httpx.MockTransport(handler or default))


def test_all_blocks_including_headers_tables_pages_and_order():
    document = ocr_blocks(RAW + RAW)
    assert len(document["pages"]) == 2
    first = document["pages"][0]["blocks"]
    assert [b["block_label"] for b in first] == ["header", "table", "footer"]
    assert first[0]["block_order"] is None and first[1]["block_order"] == 0
    assert first[1]["block_content"] == RAW[0]["res"]["parsing_res_list"][1]["block_content"]
    assert document["pages"][1]["blocks"][0]["block_ref"] == "p2:b0"
    serialized = json_text(document)
    assert "/private/" not in serialized and "DO-NOT-SEND" not in serialized


@pytest.mark.parametrize("raw", [[], {}, [{"res": {}}], [{"res": {"parsing_res_list": []}}],
    [{"res": {"parsing_res_list": [{"block_content": 42}]}}],
    [{"res": {"parsing_res_list": [{"block_content": "x" * 200001}]}}]])
def test_bad_or_oversized_blocks_never_truncated(raw):
    with pytest.raises(InputError):
        ocr_blocks(raw)


def test_schema_and_request_have_no_tools_or_local_paths():
    schema = response_schema()
    assert set(schema["properties"]["invoice"]["required"]) == set(FIELDS)
    assert schema["properties"]["invoice"]["properties"]["total_cost"]["anyOf"][0]["type"] == "number"
    request = build_request(ocr_blocks(RAW), 8192)
    assert request["generationConfig"]["responseJsonSchema"] == schema
    assert "tools" not in request and KEY not in json_text(request)
    assert "untrusted" in request["systemInstruction"]["parts"][0]["text"]


def test_assessment_preserves_decimals_nulls_and_incorrect_threshold():
    invoice, validation, review = assess(json_text(answer()), ocr_blocks(RAW))
    assert validation["valid"]
    assert invoice == answer()["invoice"]
    assert invoice[THRESHOLD] is False
    assert {"field": THRESHOLD, "code": "threshold_inconsistent_not_corrected"} in review["issues"]
    assert invoice["total_cost"] == Decimal("1100.00")
    assert type(json.loads(json_text(invoice))["total_cost"]) is float
    assert json.loads(json_text(invoice))["gst"] is None
    assert not review["semantic_accuracy_verified"]


@pytest.mark.parametrize("field,value", [
    ("total_cost", "1100.00"), ("gst", True), ("date_of_issue", "2026-02-30"),
    ("date_of_issue", "20260916"), ("paid", 1), ("buyer_identity", None),
    ("seller_abn", "123"), ("supply_type", "service"), ("expense_category", "unknown"),
    ("document_type", "bank_statement"), ("taxable_sale_extent", 101), ("gst", Decimal("1.001")),
])
def test_invalid_field_format(field, value):
    value_payload = answer()
    value_payload["invoice"][field] = value
    invoice, validation, _ = assess(json_text(value_payload), ocr_blocks(RAW))
    assert invoice is None and not validation["valid"]
    assert any(e["field"] == field for e in validation["errors"])


@pytest.mark.parametrize("text", ['{}', '[]', 'not json', '{"invoice":{},"invoice":{}}',
    '{"x":NaN}', '{"x":Infinity}', '```json\n{}\n```'])
def test_malformed_model_json(text):
    invoice, validation, _ = assess(text, ocr_blocks(RAW))
    assert invoice is None and not validation["valid"]


@pytest.mark.parametrize("mutation", ["extra", "missing", "foreign_currency", "bad_evidence"])
def test_exact_contract(mutation):
    value = answer()
    if mutation == "extra":
        value["invoice"]["subtotal"] = 1000
    elif mutation == "missing":
        del value["invoice"]["paid"]
    elif mutation == "foreign_currency":
        value["currency"] = "USD"
    else:
        value["evidence"]["total_cost"] = ["1100.00"]
    assert assess(json_text(value), ocr_blocks(RAW))[0] is None


@pytest.mark.parametrize("evidence", [[], [{"block_ref": "p9:b9", "quote": "1100.00"}],
    [{"block_ref": "p1:b1", "quote": "made up"}]])
def test_missing_or_bad_evidence_retains_values(evidence):
    value = answer()
    value["evidence"]["total_cost"] = evidence
    invoice, validation, review = assess(json_text(value), ocr_blocks(RAW))
    assert validation["valid"] and invoice["total_cost"] == 1100
    assert "total_cost" in review["fields_requiring_review"]


def test_http_contract_and_exact_provider_body(tmp_path):
    request_body = build_request(ocr_blocks(RAW), 8192)
    body = json_text(response()).encode()
    calls = []
    def handle(request):
        calls.append(request)
        assert str(request.url) == ENDPOINT and request.method == "POST"
        assert request.headers["x-goog-api-key"] == KEY
        assert KEY not in str(request.url) and KEY.encode() not in request.content
        assert json.loads(request.content) == request_body
        return httpx.Response(200, content=body)
    text, metadata = fake_client(handler=handle).generate(request_body, tmp_path)
    assert len(calls) == 1 and metadata["finish_reason"] == "STOP"
    assert (tmp_path / "llm_response.json").read_bytes() == body
    assert json.loads(text)["invoice"]["total_cost"] == 1100


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500, 503])
def test_http_failures_no_retry_or_secret_leak(tmp_path, status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={"error": f"{KEY} PRIVATE RECEIPT"}, headers={"Location": "https://evil.invalid"})
    with pytest.raises(GeminiError) as exc:
        fake_client(handler=handle).generate({}, tmp_path)
    assert len(calls) == 1 and KEY not in str(exc.value)
    assert KEY not in (tmp_path / "llm_response.json").read_text()
    assert "PRIVATE RECEIPT" not in (tmp_path / "llm_response.json").read_text()


def test_timeout_no_retry(tmp_path):
    calls = []
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout(f"secret {KEY}", request=request)
    with pytest.raises(GeminiError, match="timeout"):
        fake_client(handler=handle).generate({}, tmp_path)
    assert len(calls) == 1


@pytest.mark.parametrize("reason,code", [
    ("API_KEY_INVALID", "invalid_api_key"), ("API_KEY_EXPIRED", "expired_api_key"),
    ("API_KEY_SERVICE_BLOCKED", "api_key_restricted"), ("SERVICE_DISABLED", "api_not_enabled"),
    ("BILLING_DISABLED", "billing_not_enabled"), ("CONSUMER_INVALID", "invalid_cloud_project"),
])
def test_safe_google_error_details(tmp_path, reason, code):
    body = {"error": {"status": "INVALID_ARGUMENT", "message": f"{KEY} PRIVATE RECEIPT",
                      "details": [{"reason": reason, "metadata": {"secret": KEY, "consumer": "PRIVATE PROJECT"}}]}}
    with pytest.raises(GeminiError, match=code):
        fake_client(handler=lambda request: httpx.Response(400, json=body)).generate({}, tmp_path)
    saved = read_json(tmp_path / "llm_response.json")
    assert saved["provider_reason"] == reason and saved["provider_status"] == "INVALID_ARGUMENT"
    assert "hint" in saved
    assert KEY not in json_text(saved) and "PRIVATE" not in json_text(saved)


@pytest.mark.parametrize("message,code", [
    ("API key not valid. Please pass a valid API key.", "invalid_api_key"),
    ("API key expired. Please renew.", "expired_api_key"),
    ("Your API key was reported as leaked.", "leaked_api_key"),
    ("Free tier is not available in your country.", "region_or_billing"),
    ("Unknown name responseJsonSchema at generation_config", "invalid_request_schema"),
    ("The input schema has too many states for serving", "invalid_request_schema"),
    ("Invalid JSON payload: maxOutputTokens", "invalid_request_parameter"),
    ("Unrecognized detail", "invalid_argument"),
])
def test_safe_message_classification_does_not_store_message(tmp_path, message, code):
    body = {"error": {"status": "INVALID_ARGUMENT", "message": message + f" {KEY} PRIVATE RECEIPT"}}
    with pytest.raises(GeminiError, match=code):
        fake_client(handler=lambda request: httpx.Response(400, json=body)).generate({}, tmp_path)
    saved = read_json(tmp_path / "llm_response.json")
    assert saved["error"] == code and "hint" in saved
    assert KEY not in json_text(saved) and "PRIVATE" not in json_text(saved)
    assert "message" not in saved


def test_untrusted_error_fields_never_persist(tmp_path):
    body = {"error": {"status": KEY, "message": "PRIVATE RECEIPT", "details": [
        {"reason": KEY, "fieldViolations": [{"field": "generation_config.response_json_schema PRIVATE RECEIPT",
                                            "description": KEY}]}, {"reason": []}, None]}}
    with pytest.raises(GeminiError, match="http_400"):
        fake_client(handler=lambda request: httpx.Response(400, json=body)).generate({}, tmp_path)
    saved = read_json(tmp_path / "llm_response.json")
    assert saved["request_fields"] == ["responseJsonSchema"]
    assert "provider_status" not in saved and "provider_reason" not in saved
    assert KEY not in json_text(saved) and "PRIVATE" not in json_text(saved)


@pytest.mark.parametrize("body", [b"not JSON", b"x" * 65537], ids=["invalid-json", "oversized"])
def test_bad_error_body_retains_original_http_failure(tmp_path, body):
    with pytest.raises(GeminiError, match="http_400"):
        fake_client(handler=lambda request: httpx.Response(400, content=body)).generate({}, tmp_path)
    saved = read_json(tmp_path / "llm_response.json")
    assert saved["http_status"] == 400 and "diagnostic_status" in saved


@pytest.mark.parametrize("payload", [[], {}, {"error": "business error"}, {"promptFeedback": {"blockReason": "SAFETY"}},
    {"candidates": [{"finishReason": "MAX_TOKENS"}]},
    {"candidates": [{"finishReason": "STOP", "content": None}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"functionCall": {}}]}}]}])
def test_bad_provider_responses_saved_and_rejected(tmp_path, payload):
    with pytest.raises(GeminiError):
        fake_client(payload).generate({}, tmp_path)
    assert read_json(tmp_path / "llm_response.json") == payload


def test_provider_thought_is_not_invoice(tmp_path):
    payload = response()
    payload["candidates"][0]["content"]["parts"].insert(0, {"thought": True, "text": "NOT JSON reasoning"})
    text, _ = fake_client(payload).generate({}, tmp_path)
    assert "NOT JSON" not in text
    assert "NOT JSON" in (tmp_path / "llm_response.json").read_text()


@pytest.mark.parametrize("content,code", [(b"x" * 2_000_001, "response_too_large"), (KEY.encode(), "credential_echo"),
                                            (b"not JSON", "invalid_payload")], ids=["oversized", "secret-echo", "invalid-json"])
def test_invalid_raw_responses(tmp_path, content, code):
    with pytest.raises(GeminiError, match=code):
        fake_client(handler=lambda request: httpx.Response(200, content=content)).generate({}, tmp_path)
    if code == "invalid_payload":
        assert (tmp_path / "llm_response.json").read_bytes() == content
    else:
        assert not (tmp_path / "llm_response.json").exists()


def test_pipeline_replay_hashes_and_immutable_original(saved):
    original = saved / "outputs/original/manifest.json"
    digest = sha256(original)
    result = GeminiPipeline(saved, GeminiSettings(api_key=KEY), fake_client()).reextract("outputs/original", "gemini")
    assert result["status"] == "completed_needs_review"
    assert sha256(original) == digest
    output = saved / "outputs/gemini"
    assert read_json(output / "extracted.json")[THRESHOLD] is False
    assert (output / "raw.json").read_bytes() == (saved / "outputs/original/raw.json").read_bytes()
    manifest = read_json(output / "manifest.json")
    assert manifest["network_attempted"] and manifest["model"] == MODEL
    assert manifest["replayed_from"]["manifest_sha256"] == digest
    for name, digest in manifest["artifacts"].items():
        assert sha256(output / name) == digest
    assert KEY not in "".join(p.read_text(encoding="utf-8") for p in output.iterdir())


def test_dry_run_does_not_construct_client_or_need_key(saved, monkeypatch):
    from app.gemini import pipeline
    def forbidden(*args, **kwargs):
        pytest.fail("dry run must not construct network client")
    monkeypatch.setattr(pipeline, "GeminiClient", forbidden)
    result = GeminiPipeline(saved, GeminiSettings()).reextract("outputs/original", "prepared", dry_run=True)
    assert result["status"] == "prepared"
    assert "extracted.json" not in result["artifacts"]
    assert "llm_response.json" not in result["artifacts"]
    assert not read_json(saved / "outputs/prepared/manifest.json")["network_attempted"]


def test_pipeline_invalid_answer_retains_raw_response_without_extracted(saved):
    payload = response("not json")
    with pytest.raises(PipelineError, match="invalid_invoice_contract"):
        GeminiPipeline(saved, GeminiSettings(api_key=KEY), fake_client(payload)).reextract("outputs/original", "bad")
    output = saved / "outputs/bad"
    assert read_json(output / "manifest.json")["status"] == "failed"
    assert (output / "raw.json").exists() and (output / "llm_response.json").exists()
    assert not (output / "extracted.json").exists()
    assert not read_json(output / "validation.json")["valid"]


def test_pipeline_provider_timeout_has_safe_failure_artifacts(saved):
    def handle(request):
        raise httpx.ReadTimeout(f"{KEY} RECEIPT", request=request)
    with pytest.raises(PipelineError, match="timeout") as exc:
        GeminiPipeline(saved, GeminiSettings(api_key=KEY), fake_client(handler=handle)).reextract("outputs/original", "timeout")
    assert KEY not in str(exc.value)
    manifest = read_json(saved / "outputs/timeout/manifest.json")
    assert manifest["status"] == "failed" and manifest["network_attempted"]
    assert read_json(saved / "outputs/timeout/validation.json")["not_performed"]


@pytest.mark.parametrize("name", ["raw.json", "parsed.md"])
def test_tampering_rejected_before_network_or_output(saved, name):
    (saved / "outputs/original" / name).write_text("TAMPERED", encoding="utf-8")
    with pytest.raises(InputError, match="hash mismatch"):
        GeminiPipeline(saved, GeminiSettings()).reextract("outputs/original", "bad", dry_run=True)
    assert not (saved / "outputs/bad").exists()


@pytest.mark.parametrize("field,value", [("status", "failed"), ("source_sha256", "bad"), ("versions", []),
    ("source", "../outside.png")])
def test_bad_provenance_rejected(saved, field, value):
    path = saved / "outputs/original/manifest.json"
    manifest = read_json(path)
    del manifest["ocr_status"]
    manifest[field] = value
    write_json(path, manifest)
    with pytest.raises(InputError):
        GeminiPipeline(saved, GeminiSettings()).reextract("outputs/original", "bad", dry_run=True)


def test_source_hash_checked_when_present_and_optional_when_absent(saved):
    (saved / "invoice.png").write_bytes(b"modified")
    pipeline = GeminiPipeline(saved, GeminiSettings())
    with pytest.raises(InputError, match="Source file"):
        pipeline.reextract("outputs/original", "bad", dry_run=True)
    (saved / "invoice.png").unlink()
    assert pipeline.reextract("outputs/original", "without-image", dry_run=True)["status"] == "prepared"


def test_output_collision_and_path_escape(saved):
    pipeline = GeminiPipeline(saved, GeminiSettings())
    for directory in ("../outside", "outputs", "invoice.png"):
        with pytest.raises(InputError):
            pipeline.reextract(directory, "bad", dry_run=True)
    pipeline.reextract("outputs/original", "same", dry_run=True)
    with pytest.raises(InputError, match="already exists"):
        pipeline.reextract("outputs/original", "same", dry_run=True)


@pytest.mark.parametrize("name,value", [("GEMINI_TIMEOUT_SECONDS", "NaN"), ("GEMINI_TIMEOUT_SECONDS", "0"),
    ("GEMINI_MAX_OUTPUT_TOKENS", "oops"), ("GEMINI_MAX_OUTPUT_TOKENS", "999999")])
def test_invalid_environment(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(InputError):
        GeminiSettings.from_env(require_key=False)


def test_missing_key_and_repr(monkeypatch, saved):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(InputError, match="GEMINI_API_KEY"):
        GeminiSettings.from_env()
    assert KEY not in repr(GeminiSettings(api_key=KEY))
    with pytest.raises(InputError, match="GEMINI_API_KEY"):
        GeminiPipeline(saved, GeminiSettings()).reextract("outputs/original", "missing-key")
    assert not (saved / "outputs/missing-key").exists()


def test_cli_gemini_independent_of_qwen_ocr_settings(saved, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", saved)
    monkeypatch.setenv("LLM_PYTHON", "missing-env")
    monkeypatch.setenv("LLM_CPU_THREADS", "invalid")
    monkeypatch.setenv("PADDLEOCR_DEVICE", "invalid")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail("must not instantiate OCR/rules/Qwen")
    monkeypatch.setattr(cli, "InvoicePipeline", forbidden)
    monkeypatch.setattr(cli, "OcrPipeline", forbidden)
    assert cli.main(["extract", "outputs/original", "--extractor", "gemini", "--dry-run", "--run-id", "cli"]) == 0
    assert "prepared" in capsys.readouterr().out
    assert cli.main(["extract", "outputs/original", "--extractor", "gemini", "--run-id", "missing"]) == 1
    assert cli.main(["extract", "outputs/original", "--extractor", "rules", "--dry-run"]) == 1


def test_cli_explicit_gemini_live_mocked(saved, monkeypatch, capsys):
    from app.gemini import pipeline
    monkeypatch.setattr(cli, "ROOT", saved)
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.setattr(pipeline, "GeminiClient", lambda settings: fake_client())
    assert cli.main(["extract", "outputs/original", "--extractor", "gemini", "--run-id", "cli-live-fake"]) == 0
    output = capsys.readouterr().out
    assert "completed_needs_review" in output and "SYNTHETIC EXAMPLE" not in output and KEY not in output


def test_latest_alias_request_and_manifest(saved, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-lite-latest")
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    settings = GeminiSettings.from_env()
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url.path == "/v1beta/models/gemini-flash-lite-latest:generateContent"
        body = response()
        body["modelVersion"] = "fake-resolved-model-001"
        return httpx.Response(200, content=json_text(body))
    client = GeminiClient(settings, transport=httpx.MockTransport(handle))
    GeminiPipeline(saved, settings, client).reextract("outputs/original", "latest")
    manifest = read_json(saved / "outputs/latest/manifest.json")
    assert manifest["model"] == "gemini-flash-lite-latest"
    assert manifest["generation"]["model_version"] == "fake-resolved-model-001"
    assert len(calls) == 1


@pytest.mark.parametrize("model", ["", "https://evil.invalid", "../gemini", "gemini-pro-latest"])
def test_reject_unapproved_model(model):
    with pytest.raises(InputError, match="Unsupported GEMINI_MODEL"):
        GeminiSettings(model=model)


def test_default_model_and_no_alias_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert GeminiSettings.from_env(require_key=False).model == MODEL
    calls = []
    def handle(request):
        calls.append(str(request.url))
        return httpx.Response(404, json={"error": {"status": "NOT_FOUND"}})
    settings = GeminiSettings(api_key=KEY, model="gemini-flash-lite-latest")
    with pytest.raises(GeminiError, match="model_unavailable"):
        GeminiClient(settings, transport=httpx.MockTransport(handle)).generate({}, tmp_path)
    assert calls == [settings.endpoint]


def test_html_error_is_identified_without_disclosing_body(tmp_path):
    body = f'<!DOCTYPE html><html>PRIVATE {KEY}</html>'.encode()
    with pytest.raises(GeminiError, match="http_400"):
        fake_client(handler=lambda request: httpx.Response(400, content=body,
                    headers={"content-type": "text/html; charset=utf-8"})).generate({}, tmp_path)
    saved = read_json(tmp_path / "llm_response.json")
    assert saved["body_format"] == "html" and saved["content_type"] == "text/html"
    assert saved["diagnostic_failure"] == "body_decode_or_parse"
    assert saved["body_bytes"] == len(body)
    assert KEY not in json_text(saved) and "PRIVATE" not in json_text(saved)


def test_bom_error_json_can_be_classified(tmp_path):
    body = b'\xef\xbb\xbf' + json.dumps({"error": {"status": "INVALID_ARGUMENT",
                                    "message": "API key not valid."}}).encode()
    with pytest.raises(GeminiError, match="invalid_api_key"):
        fake_client(handler=lambda request: httpx.Response(400, content=body)).generate({}, tmp_path)
    assert read_json(tmp_path / "llm_response.json")["body_format"] == "json"


def test_metadata_probe_has_no_receipt_schema_or_generation():
    from app.gemini.diagnostics import check_model
    calls = []
    def handle(request):
        calls.append(request)
        assert request.method == "GET" and not request.content
        assert request.url.path == "/v1beta/models/gemini-flash-lite-latest"
        assert request.headers["x-goog-api-key"] == KEY
        return httpx.Response(200, json={"name": "models/fake-model", "description": KEY,
                                        "supportedGenerationMethods": ["generateContent"]})
    result = check_model(GeminiSettings(api_key=KEY, model="gemini-flash-lite-latest"),
                         transport=httpx.MockTransport(handle))
    assert result["ok"] and result["generate_content_supported"] and len(calls) == 1
    assert not result["document_sent"] and not result["generation_requested"]
    assert not result["generation_access_verified"] and KEY not in json_text(result)


@pytest.mark.parametrize("key", ["", "fake key", "fake\nkey", "中文key"])
def test_probe_rejects_invalid_local_key_without_request(key):
    from app.gemini.diagnostics import check_model
    def forbidden(request):
        pytest.fail("must not call network")
    result = check_model(GeminiSettings(api_key=key), transport=httpx.MockTransport(forbidden))
    assert not result["ok"] and "http_status" not in result


@pytest.mark.parametrize("status", [400, 403, 404])
def test_probe_errors_are_sanitized_and_no_retry(status):
    from app.gemini.diagnostics import check_model
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"status": "INVALID_ARGUMENT",
                              "message": f"API key not valid. PRIVATE {KEY}"}})
    result = check_model(GeminiSettings(api_key=KEY), transport=httpx.MockTransport(handle))
    assert result["http_status"] == status and result["error"] == "invalid_api_key"
    assert not result["ok"] and len(calls) == 1
    assert KEY not in json_text(result) and "PRIVATE" not in json_text(result)


def test_probe_timeout():
    from app.gemini.diagnostics import check_model
    def handle(request):
        raise httpx.ReadTimeout(KEY, request=request)
    result = check_model(GeminiSettings(api_key=KEY), transport=httpx.MockTransport(handle))
    assert result["error"] == "timeout" and KEY not in json_text(result)
