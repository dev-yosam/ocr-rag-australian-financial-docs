from dataclasses import dataclass, field
import math
import os
import re

from app.core.errors import InputError

MODEL = "gpt-6-luna"
ENDPOINT = "https://api.openai.com/v1/responses"


@dataclass(frozen=True)
class OpenAISettings:
    api_key: str = field(default="", repr=False)
    model: str = MODEL
    timeout: float = 180.0
    max_output_tokens: int = 8192
    reasoning_effort: str = "none"

    def __post_init__(self):
        if not re.fullmatch(r"gpt-[A-Za-z0-9][A-Za-z0-9._-]{0,99}", self.model):
            raise InputError("Invalid OPENAI_MODEL; use an explicit GPT model ID")
        if not math.isfinite(self.timeout) or not 1 <= self.timeout <= 600:
            raise InputError("OPENAI_TIMEOUT_SECONDS must be between 1 and 600")
        if not 512 <= self.max_output_tokens <= 32768:
            raise InputError("OPENAI_MAX_OUTPUT_TOKENS must be between 512 and 32768")
        if self.reasoning_effort not in ("none", "low", "medium", "high"):
            raise InputError("Invalid OPENAI_REASONING_EFFORT")
        if self.api_key and (len(self.api_key) < 20 or not self.api_key.isascii()
                             or any(c.isspace() or c in "\"'" for c in self.api_key)):
            raise InputError("OPENAI_API_KEY looks incomplete or contains invalid characters; paste the full key")

    @classmethod
    def from_env(cls):
        try:
            result = cls(
                api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
                model=(os.environ.get("OPENAI_MODEL") or MODEL).strip(),
                timeout=float(os.environ.get("OPENAI_TIMEOUT_SECONDS") or "180"),
                max_output_tokens=int(os.environ.get("OPENAI_MAX_OUTPUT_TOKENS") or "8192"),
                reasoning_effort=(os.environ.get("OPENAI_REASONING_EFFORT") or "none").strip(),
            )
        except ValueError:
            raise InputError("Invalid OpenAI configuration") from None
        if not result.api_key:
            raise InputError("OPENAI_API_KEY is required")
        return result
