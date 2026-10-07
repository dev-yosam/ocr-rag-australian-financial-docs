"""One Responses API call, with injectable transport and sanitized failures."""
from pathlib import Path
import re
import time

import httpx

from app.core.errors import ExtractionError
from app.core.files import json_text, write_json
from app.extraction.block_contract import strict_json
from app.openai_extraction.config import ENDPOINT, OpenAISettings

MAX_RESPONSE_BYTES = 2_000_000
ERROR_CODES = {
    "invalid_api_key", "insufficient_quota", "rate_limit_exceeded", "model_not_found",
    "context_length_exceeded", "unsupported_parameter", "unsupported_value",
    "invalid_json_schema", "invalid_request_error", "permission_denied",
}
HINTS = {
    "authentication": "請重新設定完整 OPENAI_API_KEY。",
    "invalid_api_key": "API key 無效，請重新複製完整金鑰。",
    "insufficient_quota": "請檢查 OpenAI 專案的計費、額度與使用限制。",
    "rate_limit": "已達速率限制；稍後以新的 run ID 重試。",
    "rate_limit_exceeded": "已達速率限制；稍後以新的 run ID 重試。",
    "permission": "請檢查 API key 權限與專案模型存取權。",
    "model_unavailable": "請確認 OPENAI_MODEL 名稱與帳號存取權；不會自動換模型。",
    "model_not_found": "請確認 OPENAI_MODEL 名稱與帳號存取權；不會自動換模型。",
    "invalid_json_schema": "OpenAI 拒絕輸出 schema；請檢查模型與 schema 相容性。",
    "unsupported_parameter": "模型不支援目前參數；請檢查 llm_request.json。",
    "unsupported_value": "模型不支援目前參數值；請檢查 reasoning effort 等設定。",
}


class OpenAIError(ExtractionError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(f"OpenAI request failed: {code}")


def _read_body(response: httpx.Response, started: float, timeout: float, limit: int) -> bytes:
    content = bytearray()
    for chunk in response.iter_bytes():
        content.extend(chunk)
        if len(content) > limit:
            raise OpenAIError("response_too_large")
        if time.monotonic() - started > timeout:
            raise OpenAIError("timeout")
    return bytes(content)


def _http_error(response: httpx.Response, started: float, timeout: float) -> dict:
    status = response.status_code
    code = {401: "authentication", 403: "permission", 404: "model_unavailable",
            429: "rate_limit"}.get(status, f"http_{status}")
    result = {"http_status": status, "error": code}
    mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    result["content_type"] = mime if mime in ("application/json", "text/html", "text/plain") else "other_or_missing"
    try:
        body = _read_body(response, started, timeout, 65536)
        result["body_bytes"] = len(body)
        payload = strict_json(body.decode("utf-8-sig"))
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            for name in ("code", "type"):
                value = error.get(name)
                if isinstance(value, str) and value in ERROR_CODES:
                    result["provider_" + name] = value
                    if name == "code" or result["error"] == code:
                        result["error"] = value
            param = error.get("param")
            if isinstance(param, str) and param in ("model", "reasoning.effort", "text.format", "text.format.schema", "max_output_tokens"):
                result["request_parameter"] = param
    except (ValueError, TypeError, UnicodeError, RecursionError, httpx.HTTPError, OpenAIError):
        result["diagnostic_status"] = "error_body_unavailable"
    if result["error"] in HINTS:
        result["hint"] = HINTS[result["error"]]
    return result


def _completed_text(payload: object) -> str:
    if not isinstance(payload, dict) or payload.get("error"):
        raise OpenAIError("invalid_payload")
    if payload.get("status") != "completed":
        raise OpenAIError("incomplete_generation")
    output = payload.get("output")
    if not isinstance(output, list) or not output:
        raise OpenAIError("missing_text")
    messages = []
    for item in output:
        if not isinstance(item, dict):
            raise OpenAIError("invalid_output")
        if item.get("type") == "reasoning":
            continue
        if item.get("type") != "message" or item.get("role") != "assistant":
            raise OpenAIError("unexpected_output")
        if item.get("status") != "completed":
            raise OpenAIError("incomplete_generation")
        parts = item.get("content")
        if not isinstance(parts, list) or not parts:
            raise OpenAIError("missing_text")
        texts = []
        for part in parts:
            if not isinstance(part, dict):
                raise OpenAIError("invalid_output")
            if part.get("type") == "refusal":
                raise OpenAIError("refused")
            if part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                raise OpenAIError("invalid_output")
            texts.append(part["text"])
        messages.append("".join(texts))
    if len(messages) != 1 or not messages[0].strip():
        raise OpenAIError("missing_or_multiple_messages")
    return messages[0]


def _usage(payload: dict) -> dict:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return {}
    result = {name: usage[name] for name in ("input_tokens", "output_tokens", "total_tokens")
              if type(usage.get(name)) is int and usage[name] >= 0}
    for section, name in (("input_tokens_details", "cached_tokens"), ("output_tokens_details", "reasoning_tokens")):
        details = usage.get(section)
        if isinstance(details, dict) and type(details.get(name)) is int and details[name] >= 0:
            result[section] = {name: details[name]}
    return result


class OpenAIClient:
    def __init__(self, settings: OpenAISettings, *, transport=None):
        self.settings, self.transport = settings, transport

    def generate(self, request: dict, output: Path) -> tuple[str, dict]:
        if not self.settings.api_key:
            raise OpenAIError("missing_api_key")
        started = time.monotonic()
        try:
            with httpx.Client(timeout=self.settings.timeout, trust_env=False,
                              follow_redirects=False, transport=self.transport) as client:
                with client.stream("POST", ENDPOINT,
                                   headers={"Authorization": f"Bearer {self.settings.api_key}",
                                            "Content-Type": "application/json"},
                                   content=json_text(request).encode("utf-8")) as response:
                    if response.status_code != 200:
                        diagnostic = _http_error(response, started, self.settings.timeout)
                        write_json(output / "llm_response.json", diagnostic)
                        raise OpenAIError(diagnostic["error"])
                    body = _read_body(response, started, self.settings.timeout, MAX_RESPONSE_BYTES)
            if self.settings.api_key.encode() in body:
                raise OpenAIError("credential_echo")
            try:
                payload = strict_json(body.decode("utf-8-sig"))
            except (ValueError, UnicodeError, RecursionError):
                # Invalid bodies are diagnostics, not trustworthy provider output.
                raise OpenAIError("invalid_payload") from None
            if self.settings.api_key in json_text(payload):
                raise OpenAIError("credential_echo")
            (output / "llm_response.json").write_bytes(body)
            text = _completed_text(payload)
            metadata = {"http_status": 200, "status": "completed", "usage": _usage(payload),
                        "elapsed_seconds": round(time.monotonic() - started, 3)}
            for source, target in (("model", "model_version"), ("id", "response_id")):
                value = payload.get(source)
                if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,160}", value):
                    metadata[target] = value
            return text, metadata
        except httpx.TimeoutException:
            raise OpenAIError("timeout") from None
        except httpx.HTTPError:
            raise OpenAIError("transport") from None
        except (ValueError, TypeError, AttributeError, UnicodeError, RecursionError):
            raise OpenAIError("invalid_payload") from None
