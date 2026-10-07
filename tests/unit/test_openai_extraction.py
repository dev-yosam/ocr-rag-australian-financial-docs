"""Synthetic saved OCR + fake HTTP; no real API keys or cloud calls."""
from copy import deepcopy
from decimal import Decimal
import json

import httpx
import pytest

from app import cli
from app.core.errors import InputError, PipelineError
from app.core.files import json_text, read_json, sha256, write_json
from app.extraction.block_contract import FIELDS, THRESHOLD, SYSTEM, ocr_blocks, response_schema
from app.gemini.contract import build_request as gemini_request
from app.openai_extraction.client import OpenAIClient, OpenAIError
from app.openai_extraction.config import ENDPOINT, MODEL, OpenAISettings
from app.openai_extraction.contract import build_request
from app.openai_extraction.pipeline import OpenAIPipeline
from app.schemas.invoice import TaxInvoice

KEY = "sk-SYNTHETIC-NOT-A-REAL-API-KEY"
RAW = [{"res": {"input_path": "DO-NOT-SEND", "parsing_res_list": [
    {"block_label": "header", "block_content": "SYNTHETIC MERCHANT", "block_bbox": [0, 0, 10, 10]},
    {"block_label": "table", "block_content": "<table><tr><td>Total AUD 1100.00</td></tr></table>"},
    {"block_label": "footer", "block_content": "SYNTHETIC FOOTER"},
]}}]


def answer():
    invoice = TaxInvoice().model_dump(mode="python")
    invoice.update(total_cost=Decimal("1100.00"))
    invoice[THRESHOLD] = False  # Deliberately inconsistent: retain, do not repair.
    evidence = {name: [] for name in FIELDS}
    evidence["total_cost"] = [{"block_ref": "p1:b1", "quote": "1100.00"}]
    return {"invoice": invoice, "evidence": evidence, "currency": "AUD"}


def payload(text=None):
    return {"id": "resp_synthetic", "model": MODEL, "status": "completed", "error": None,
            "output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": json_text(answer()) if text is None else text}]}],
            "usage": {"input_tokens": 100, "output_tokens": 200, "total_tokens": 300,
                      "input_tokens_details": {"cached_tokens": 50},
                      "output_tokens_details": {"reasoning_tokens": 20}, "secret": KEY}}


@pytest.fixture
def saved(repo):
    output = repo / "outputs/original"
    output.mkdir(parents=True)
    write_json(output / "raw.json", RAW)
    (output / "parsed.md").write_text("SYNTHETIC MARKDOWN", encoding="utf-8")
    write_json(output / "manifest.json", {
        "ocr_status": "completed", "source": "invoice.png", "versions": {"fixture": "FAKE"},
        "source_sha256": sha256(repo / "invoice.png"),
        "artifacts": {name: sha256(output / name) for name in ("raw.json", "parsed.md")},
    })
    return repo


def response_body():
    value = payload()
    del value["usage"]["secret"]
    return value


def fake_client(body=None, handler=None):
    return OpenAIClient(OpenAISettings(api_key=KEY), transport=httpx.MockTransport(
        handler or (lambda request: httpx.Response(200, content=json_text(response_body() if body is None else body).encode()))))


def test_shared_prompt_schema_and_complete_input():
    document = ocr_blocks(RAW + RAW)
    request = build_request(document, OpenAISettings())
    other = gemini_request(document, 8192)
    assert request["instructions"] == SYSTEM == other["systemInstruction"]["parts"][0]["text"]
    assert request["text"]["format"]["schema"] == response_schema() == other["generationConfig"]["responseJsonSchema"]
    assert request["text"]["format"]["strict"] is True
    assert request["store"] is False and "tools" not in request
    assert request["input"][0]["content"][0]["text"] == json_text(document)
    assert len(document["pages"]) == 2
    assert "DO-NOT-SEND" not in json_text(request) and KEY not in json_text(request)
    # Every object must be closed and all keys required for strict structured output.
    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for child in node.values():
                check(child)
        elif isinstance(node, list):
            for child in node:
                check(child)
    check(request["text"]["format"]["schema"])


def test_wire_request_response_and_usage(tmp_path):
    body = json_text(response_body()).encode()
    request = build_request(ocr_blocks(RAW), OpenAISettings())
    calls = []
    def handler(req):
        calls.append(req)
        assert req.method == "POST" and str(req.url) == ENDPOINT
        assert req.headers["Authorization"] == f"Bearer {KEY}"
        assert KEY not in str(req.url) and KEY.encode() not in req.content
        assert json.loads(req.content) == request
        return httpx.Response(200, content=body)
    text, metadata = fake_client(handler=handler).generate(request, tmp_path)
    assert len(calls) == 1
    assert (tmp_path / "llm_response.json").read_bytes() == body
    assert json.loads(text)["invoice"]["total_cost"] == 1100
    assert metadata["usage"]["total_tokens"] == 300
    assert metadata["usage"]["output_tokens_details"]["reasoning_tokens"] == 20
    assert metadata["model_version"] == MODEL


@pytest.mark.parametrize("status,code", [(301, "http_301"), (400, "http_400"), (401, "authentication"),
    (403, "permission"), (404, "model_unavailable"), (429, "rate_limit"), (500, "http_500")])
def test_failures_do_not_retry_redirect_or_leak(tmp_path, status, code):
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(status, json={"error": {"message": KEY + " PRIVATE DATA", "code": KEY}},
                              headers={"Location": "https://example.invalid"})
    with pytest.raises(OpenAIError, match=code):
        fake_client(handler=handler).generate({}, tmp_path)
    assert len(calls) == 1
    diagnostic = (tmp_path / "llm_response.json").read_text(encoding="utf-8")
    assert KEY not in diagnostic and "PRIVATE DATA" not in diagnostic


@pytest.mark.parametrize("code", ["invalid_api_key", "insufficient_quota", "invalid_json_schema", "unsupported_value"])
def test_actionable_provider_error(tmp_path, code):
    def handler(req):
        return httpx.Response(400, json={"error": {"code": code, "type": "invalid_request_error",
            "param": "reasoning.effort", "message": KEY + " PRIVATE DATA"}})
    with pytest.raises(OpenAIError, match=code):
        fake_client(handler=handler).generate({}, tmp_path)
    error = read_json(tmp_path / "llm_response.json")
    assert error["error"] == code and "hint" in error
    assert KEY not in json_text(error)


@pytest.mark.parametrize("mutation,code", [
    ("incomplete", "incomplete_generation"), ("refusal", "refused"), ("tool", "unexpected_output"),
    ("empty", "missing_text"), ("messages", "missing_or_multiple_messages"),
    ("partial_message", "incomplete_generation"), ("non_text", "invalid_output"),
])
def test_response_states(tmp_path, mutation, code):
    value = response_body()
    message = value["output"][1]
    if mutation == "incomplete":
        value["status"] = "incomplete"
    elif mutation == "refusal":
        message["content"] = [{"type": "refusal", "refusal": "synthetic refusal"}]
    elif mutation == "tool":
        value["output"].append({"type": "function_call"})
    elif mutation == "empty":
        value["output"] = []
    elif mutation == "messages":
        value["output"].append(deepcopy(message))
    elif mutation == "partial_message":
        message["status"] = "in_progress"
    else:
        message["content"] = [{"type": "output_text", "text": 42}]
    with pytest.raises(OpenAIError, match=code):
        fake_client(value).generate({}, tmp_path)
    assert read_json(tmp_path / "llm_response.json") == value


@pytest.mark.parametrize("body,code", [(b"x" * 2000001, "response_too_large"), (b"not JSON", "invalid_payload"),
    (b'{"status":"completed","status":"completed"}', "invalid_payload"),
    (json_text({"secret": KEY}).encode(), "credential_echo"),
    (json.dumps({"secret": KEY}).replace("sk-", "\\u0073k-").encode(), "credential_echo")],
    ids=["oversized", "non-json", "duplicate-keys", "secret-echo", "escaped-secret"])
def test_invalid_body_not_persisted(tmp_path, body, code):
    with pytest.raises(OpenAIError, match=code):
        fake_client(handler=lambda req: httpx.Response(200, content=body)).generate({}, tmp_path)
    assert not (tmp_path / "llm_response.json").exists()


def test_timeout_is_sanitized(tmp_path):
    calls = []
    def handler(req):
        calls.append(req)
        raise httpx.ReadTimeout(KEY, request=req)
    with pytest.raises(OpenAIError, match="timeout") as caught:
        fake_client(handler=handler).generate({}, tmp_path)
    assert len(calls) == 1 and KEY not in str(caught.value)


def test_replay_preserves_original_values_provenance_and_usage(saved):
    original = {p.name: p.read_bytes() for p in (saved / "outputs/original").iterdir()}
    result = OpenAIPipeline(saved, OpenAISettings(api_key=KEY), fake_client()).reextract("outputs/original", "gpt-test")
    output = saved / "outputs/gpt-test"
    assert result["status"] == "completed_needs_review"
    assert read_json(output / "extracted.json") == answer()["invoice"]
    manifest = read_json(output / "manifest.json")
    assert manifest["provider"] == "openai_api" and manifest["ocr_status"] == "reused"
    assert not manifest["semantic_accuracy_verified"]
    assert manifest["generation"]["usage"]["input_tokens"] == 100
    assert manifest["replayed_from"]["manifest_sha256"] == sha256(saved / "outputs/original/manifest.json")
    for name, digest in manifest["artifacts"].items():
        assert sha256(output / name) == digest
        assert KEY not in (output / name).read_text(encoding="utf-8")
    assert {p.name: p.read_bytes() for p in (saved / "outputs/original").iterdir()} == original
    with pytest.raises(InputError, match="already exists"):
        OpenAIPipeline(saved, OpenAISettings(api_key=KEY), fake_client()).reextract("outputs/original", "gpt-test")


@pytest.mark.parametrize("kind", ["contract", "http", "timeout"])
def test_pipeline_failure_never_writes_extracted(saved, kind):
    def handler(req):
        if kind == "timeout":
            raise httpx.ReadTimeout(KEY, request=req)
        value = response_body()
        value["output"][1]["content"][0]["text"] = "{}"
        return httpx.Response(401 if kind == "http" else 200, content=json_text(value).encode())
    with pytest.raises(PipelineError):
        OpenAIPipeline(saved, OpenAISettings(api_key=KEY), fake_client(handler=handler)).reextract("outputs/original", "failed")
    output = saved / "outputs/failed"
    assert not (output / "extracted.json").exists()
    assert read_json(output / "manifest.json")["status"] == "failed"
    assert read_json(output / "validation.json")["valid"] is False


@pytest.mark.parametrize("name", ["raw.json", "parsed.md", "source"])
def test_tamper_rejected_before_network(saved, name):
    path = saved / "invoice.png" if name == "source" else saved / "outputs/original" / name
    path.write_bytes(b"tampered")
    with pytest.raises(InputError):
        OpenAIPipeline(saved, OpenAISettings(api_key=KEY)).reextract("outputs/original", "tampered")
    assert not (saved / "outputs/tampered").exists()


@pytest.mark.parametrize("kwargs", [{"api_key": "x"}, {"api_key": KEY + "\n"}, {"api_key": "中" * 30},
    {"model": "../bad"}, {"timeout": float("nan")}, {"timeout": 0}, {"max_output_tokens": 20},
    {"reasoning_effort": "invalid"}])
def test_settings_reject_invalid_input(kwargs):
    with pytest.raises(InputError):
        OpenAISettings(**kwargs)


def test_env_selection_and_secret_repr(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "low")
    settings = OpenAISettings.from_env()
    assert settings.model == "gpt-5.4-mini" and settings.reasoning_effort == "low"
    assert KEY not in repr(settings)
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(InputError, match="OPENAI_API_KEY is required"):
        OpenAISettings.from_env()


def test_cli_calls_openai_without_ocr_llm_environment(saved, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", saved)
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.setenv("LLM_DEVICE", "INVALID")
    monkeypatch.setenv("PADDLEOCR_DEVICE", "INVALID")
    bound = fake_client().generate
    monkeypatch.setattr(OpenAIClient, "generate", lambda self, request, output: bound(request, output))
    assert cli.main(["extract", "outputs/original", "--extractor", "openai", "--run-id", "cli-gpt"]) == 0
    assert "completed_needs_review" in capsys.readouterr().out


def test_cli_missing_key_is_actionable(monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cli.main(["extract", "outputs/unused", "--extractor", "openai"]) == 1
    assert "OPENAI_API_KEY is required" in capsys.readouterr().err
