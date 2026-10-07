"""Explicit Gemini models.get connectivity check; no generation or document upload."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.errors import InputError
from app.core.files import json_text
from app.gemini.config import GeminiSettings
from app.gemini.diagnostics import check_model


def main() -> int:
    try:
        result = check_model(GeminiSettings.from_env())
        print(json_text(result))
        return 0 if result["ok"] else 1
    except InputError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
