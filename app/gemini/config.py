from dataclasses import dataclass, field
import os

from app.core.errors import InputError

MODEL = "gemini-3.5-flash-lite"
ALLOWED_MODELS = (MODEL, "gemini-flash-lite-latest")
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str = field(default="", repr=False)
    timeout: float = 120.0
    max_output_tokens: int = 8192
    model: str = MODEL

    def __post_init__(self):
        if self.model not in ALLOWED_MODELS:
            raise InputError("Unsupported GEMINI_MODEL; select gemini-3.5-flash-lite or gemini-flash-lite-latest")
        if not 1 <= self.timeout <= 600:
            raise InputError("Invalid Gemini timeout")
        if not 512 <= self.max_output_tokens <= 16384:
            raise InputError("Invalid Gemini output token limit")

    @property
    def endpoint(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    @classmethod
    def from_env(cls, *, require_key: bool = True):
        try:
            result = cls(
                api_key=(os.environ.get("GEMINI_API_KEY") or "").strip() if require_key else "",
                timeout=float(os.environ.get("GEMINI_TIMEOUT_SECONDS") or "120"),
                max_output_tokens=int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS") or "8192"),
                model=(os.environ.get("GEMINI_MODEL") or MODEL).strip(),
            )
        except ValueError:
            raise InputError("Invalid Gemini configuration") from None
        if require_key and not result.api_key:
            raise InputError("GEMINI_API_KEY is required")
        return result
