"""Responses API wire format; business semantics are shared with Gemini."""
from app.core.files import json_text
from app.extraction.block_contract import SYSTEM, response_schema
from app.openai_extraction.config import OpenAISettings

PROMPT_VERSION = "tirbic-15-v2-openai-blocks-v1"


def build_request(document: dict, settings: OpenAISettings) -> dict:
    return {
        "model": settings.model,
        "instructions": SYSTEM,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": json_text(document)}]}],
        "text": {"format": {"type": "json_schema", "name": "tirbic_invoice",
                            "strict": True, "schema": response_schema()}},
        "reasoning": {"effort": settings.reasoning_effort},
        "max_output_tokens": settings.max_output_tokens,
        "store": False,
    }
