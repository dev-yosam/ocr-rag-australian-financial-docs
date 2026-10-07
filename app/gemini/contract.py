"""Gemini wire format using the shared OCR-block extraction contract."""
from app.core.files import json_text
from app.extraction.block_contract import (
    SYSTEM, FIELDS, DATES, NUMBERS, BOOLS, THRESHOLD, MAX_INPUT_CHARS,
    assess, ocr_blocks, response_schema, strict_json,
)

# Preserve the historical Gemini prompt identifier; prompt text is unchanged.
PROMPT_VERSION = "tirbic-15-v2-gemini-blocks-v1"


def build_request(document: dict, max_output_tokens: int) -> dict:
    return {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": json_text(document)}]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "responseJsonSchema": response_schema(),
                             "candidateCount": 1, "maxOutputTokens": max_output_tokens},
    }
