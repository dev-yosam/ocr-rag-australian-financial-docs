"""Check the isolated text-LLM runtime without downloading or loading weights."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import Settings
from app.llm.models import verify_model
from app.llm.runtime import activate_device, check_packages
from app.llm.worker import offline_runtime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", action="store_true", help="Also verify the full local model checksum set")
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        offline_runtime(settings.root)
        versions = check_packages()
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        device, dtype = activate_device(torch, settings.llm_device, settings.llm_dtype, settings.llm_threads)
        for name, value in versions.items():
            print(f"{name}={value}")
        print(f"LLM computation passed: {device}, dtype={dtype}")
        print("LLM weights not loaded; this is not extraction acceptance")
        if args.models:
            _, identity = verify_model(settings.root)
            print(f"Model checksums passed: {identity['repository']} revision={identity['revision']}")
        return 0
    except Exception:
        print("LLM environment check failed; check the pinned environment and selected device", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
