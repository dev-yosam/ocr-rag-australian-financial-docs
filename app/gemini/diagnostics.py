"""One models.get request, with no receipt, prompt, schema or generation call."""
import time

import httpx

from app.gemini.config import GeminiSettings
from app.gemini.contract import strict_json
from app.gemini.errors import safe_http_error


def check_model(settings: GeminiSettings, *, transport=None) -> dict:
    result = {"check": "models.get", "model": settings.model,
              "generation_requested": False, "document_sent": False,
              "key_present": bool(settings.api_key),
              "key_contains_whitespace": any(c.isspace() for c in settings.api_key),
              "key_ascii": settings.api_key.isascii(), "ok": False}
    if not settings.api_key:
        return {**result, "error": "missing_api_key"}
    if result["key_contains_whitespace"] or not result["key_ascii"]:
        return {**result, "error": "key_contains_invalid_header_characters"}
    started = time.monotonic()
    try:
        with httpx.Client(timeout=settings.timeout, trust_env=False, follow_redirects=False,
                          transport=transport) as client:
            with client.stream("GET", settings.endpoint.removesuffix(":generateContent"),
                               headers={"x-goog-api-key": settings.api_key}) as response:
                result["http_status"] = response.status_code
                if response.status_code != 200:
                    return {**result, **safe_http_error(response, started=started, timeout=settings.timeout)}
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 262144 or time.monotonic() - started > settings.timeout:
                        return {**result, "error": "metadata_response_limit"}
                payload = strict_json(data.decode("utf-8-sig"))
                if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
                    return {**result, "error": "invalid_metadata_response"}
                methods = payload.get("supportedGenerationMethods")
                if not isinstance(methods, list) or any(not isinstance(m, str) for m in methods):
                    return {**result, "error": "invalid_metadata_response"}
                return {**result, "ok": True, "generate_content_supported": "generateContent" in methods,
                        "generation_access_verified": False}
    except httpx.TimeoutException:
        return {**result, "error": "timeout"}
    except httpx.HTTPError:
        return {**result, "error": "transport"}
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return {**result, "error": "invalid_metadata_response"}
