"""Reduce Google errors to fixed diagnostics; never retain arbitrary provider text."""
import time

import httpx

from app.gemini.contract import strict_json

REASONS = {
    "API_KEY_INVALID": "invalid_api_key",
    "API_KEY_EXPIRED": "expired_api_key",
    "API_KEY_SERVICE_BLOCKED": "api_key_restricted",
    "API_KEY_HTTP_REFERRER_BLOCKED": "api_key_restricted",
    "API_KEY_IP_ADDRESS_BLOCKED": "api_key_restricted",
    "SERVICE_DISABLED": "api_not_enabled",
    "BILLING_DISABLED": "billing_not_enabled",
    "CONSUMER_INVALID": "invalid_cloud_project",
}
STATUSES = {"INVALID_ARGUMENT", "FAILED_PRECONDITION", "UNAUTHENTICATED", "PERMISSION_DENIED",
            "NOT_FOUND", "RESOURCE_EXHAUSTED", "INTERNAL", "UNAVAILABLE"}
HINTS = {
    "invalid_api_key": "Google 回報 key 無效；請重新複製完整 Gemini API key。",
    "expired_api_key": "Google 回報 key 已過期；請在 AI Studio 更新 key。",
    "leaked_api_key": "Google 回報 key 已因外洩而封鎖；請建立替代 key。",
    "api_key_restricted": "請檢查 key 的 API、IP 或應用程式限制是否允許目前呼叫。",
    "api_not_enabled": "請確認 key 所屬 project 已啟用 Generative Language API。",
    "billing_not_enabled": "請檢查 key 所屬 project 的 Gemini API 計費設定。",
    "invalid_cloud_project": "請檢查 key 所屬 Google Cloud project 是否仍有效。",
    "invalid_request_schema": "Google 指出輸出 schema 有問題；需檢查 schema 相容性或複雜度。",
    "invalid_request_parameter": "Google 指出請求參數或 JSON 格式有問題。",
    "region_or_billing": "Google 指出地區或免費方案限制；請檢查所在地與計費資格。",
    "invalid_argument": "Google 回報參數錯誤，但未辨識到更細的安全分類；尚不能判定原因。",
}


def safe_http_error(response: httpx.Response, *, started: float, timeout: float) -> dict:
    status = response.status_code
    code = {401: "authentication", 403: "permission", 429: "rate_limit",
            404: "model_unavailable"}.get(status, f"http_{status}")
    result = {"http_status": status, "error": code}
    mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    result["content_type"] = mime if mime in ("application/json", "text/html", "text/plain") else "other_or_missing"
    try:
        data = bytearray()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data) > 65_536 or time.monotonic() - started > timeout:
                result["diagnostic_status"] = "error_body_limit"
                return result
        result["body_bytes"] = len(data)
        leading = bytes(data).lstrip().lower()
        result["body_format"] = "empty" if not leading else "html" if leading.startswith((b"<!doctype html", b"<html")) else "non_json"
        payload = strict_json(data.decode("utf-8-sig"))
        result["body_format"] = "json"
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            return result
        provider_status = error.get("status")
        if isinstance(provider_status, str) and provider_status in STATUSES:
            result["provider_status"] = provider_status
        details = error.get("details", [])
        details = details if isinstance(details, list) else []
        for detail in details:
            if not isinstance(detail, dict):
                continue
            reason = detail.get("reason")
            if isinstance(reason, str) and reason in REASONS:
                result.update(error=REASONS[reason], provider_reason=reason)
                break
        message = error.get("message", "")
        message = message.lower() if isinstance(message, str) else ""
        if result["error"] == code:
            # Classify in memory; never copy provider message, metadata or values.
            if "api key not valid" in message or "api key is invalid" in message:
                result["error"] = "invalid_api_key"
            elif "api key expired" in message:
                result["error"] = "expired_api_key"
            elif "reported as leaked" in message:
                result["error"] = "leaked_api_key"
            elif "free tier" in message and ("country" in message or "region" in message):
                result["error"] = "region_or_billing"
            elif provider_status == "INVALID_ARGUMENT":
                result["error"] = "invalid_argument"
                if any(term in message for term in ("response_json_schema", "responsejsonschema",
                                                     "response_schema", "input schema", "output schema")):
                    result["error"] = "invalid_request_schema"
                elif "invalid json payload" in message or "unknown name" in message:
                    result["error"] = "invalid_request_parameter"
        # Persist only known request field names, not arbitrary field paths/values.
        field_text = message + " " + " ".join(
            violation["field"] for detail in details if isinstance(detail, dict)
            and isinstance(detail.get("fieldViolations"), list)
            for violation in detail["fieldViolations"] if isinstance(violation, dict)
            and isinstance(violation.get("field"), str)
        ).lower()
        fields = [name for name, aliases in {
            "responseJsonSchema": ("responsejsonschema", "response_json_schema"),
            "responseMimeType": ("responsemimetype", "response_mime_type"),
            "maxOutputTokens": ("maxoutputtokens", "max_output_tokens"),
            "candidateCount": ("candidatecount", "candidate_count"),
            "systemInstruction": ("systeminstruction", "system_instruction"),
        }.items() if any(alias in field_text for alias in aliases)]
        if fields:
            result["request_fields"] = fields
    except (ValueError, TypeError, UnicodeError, RecursionError, httpx.HTTPError) as exc:
        result["diagnostic_status"] = "error_body_unavailable"
        result["diagnostic_failure"] = "transport_read" if isinstance(exc, httpx.HTTPError) else "body_decode_or_parse"
    if result["error"] in HINTS:
        result["hint"] = HINTS[result["error"]]
    return result
