"""Explicit anonymous download of the pinned Qwen text model (or offline check)."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import ROOT
from app.core.errors import PipelineError
from app.llm.models import prepare_model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true",
                        help="Verify existing model files without any network access")
    args = parser.parse_args()
    try:
        prepare_model(ROOT, verify_only=args.verify_only,
                      progress=lambda message: print(message, flush=True))
    except PipelineError as error:
        print(str(error), file=sys.stderr)
        return 1
    print("Qwen3-4B-Instruct-2507 model verified; extraction can now run offline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
