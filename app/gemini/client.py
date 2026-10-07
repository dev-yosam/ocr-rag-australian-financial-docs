"""One explicit HTTPS request. No retries, redirects, tools or environment proxies."""
from pathlib import Path
import re
import time

import httpx

from app.core.errors import ExtractionError
from app.core.files import json_text, write_json
from app.gemini.config import GeminiSettings
from app.gemini.contract import strict_json
from app.gemini.errors import safe_http_error

MAX_RESPONSE_BYTES = 2_000_000


class GeminiError(ExtractionError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(f"Gemini request failed: {code}")


class GeminiClient:
    def __init__(self, settings: GeminiSettings, *, transport=None):
        self.settings = settings
        self.transport = transport

    def generate(self, request: dict, output: Path) -> tuple[str, dict]:
        if not self.settings.api_key:
            raise GeminiError("missing_api_key")
        started = time.monotonic()
        try:
            with httpx.Client(timeout=self.settings.timeout, trust_env=False,
                              follow_redirects=False, transport=self.transport) as client:
                with client.stream("POST", self.settings.endpoint,
                                   headers={"x-goog-api-key": self.settings.api_key,
                                            "Content-Type": "application/json"},
                                   content=json_text(request).encode("utf-8")) as response:
                    status = response.status_code
                    if status != 200:
                        diagnostic = safe_http_error(response, started=started, timeout=self.settings.timeout)
                        write_json(output / "llm_response.json", diagnostic)
                        raise GeminiError(diagnostic["error"])
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_RESPONSE_BYTES:
                            raise GeminiError("response_too_large")
                        if time.monotonic() - started > self.settings.timeout:
                            raise GeminiError("timeout")
            # Successful provider body is retained verbatim, even if invalid JSON.
            # A provider echo of the authentication header is never persisted.
            if self.settings.api_key.encode() in content:
                raise GeminiError("credential_echo")
            (output / "llm_response.json").write_bytes(content)
            payload = strict_json(content.decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("error"):
                raise GeminiError("invalid_payload")
            feedback = payload.get("promptFeedback", {})
            if not isinstance(feedback, dict) or feedback.get("blockReason"):
                raise GeminiError("prompt_blocked")
            candidates = payload.get("candidates")
            if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
                raise GeminiError("missing_candidate")
            candidate = candidates[0]
            if candidate.get("finishReason") != "STOP":
                raise GeminiError("incomplete_generation")
            parts = candidate.get("content", {}).get("parts", [])
            if not isinstance(parts, list) or any(not isinstance(p, dict) for p in parts):
                raise GeminiError("invalid_parts")
            visible = [p for p in parts if not p.get("thought", False)]
            if not visible or any(not isinstance(p.get("text"), str) or "functionCall" in p for p in visible):
                raise GeminiError("missing_text")
            text = "".join(p["text"] for p in visible)
            if not text.strip():
                raise GeminiError("missing_text")
            # Only constrained model-version metadata is copied out of the raw response.
            metadata = {"http_status": 200, "finish_reason": "STOP",
                        "elapsed_seconds": round(time.monotonic() - started, 3)}
            resolved_model = payload.get("modelVersion")
            if isinstance(resolved_model, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,120}", resolved_model):
                metadata["model_version"] = resolved_model
            return text, metadata
        except httpx.TimeoutException:
            raise GeminiError("timeout") from None
        except httpx.HTTPError:
            raise GeminiError("transport") from None
        except (ValueError, TypeError, AttributeError, UnicodeError, RecursionError):
            raise GeminiError("invalid_payload") from None
