"""Content-free OCR import preflight, without contacting model providers."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import ROOT, local_runtime
from app.paddleocr.worker import EXPECTED, deny_network
import importlib.metadata


def main() -> int:
    local_runtime(ROOT)
    sys.addaudithook(deny_network)
    for name, version in EXPECTED.items():
        installed = importlib.metadata.version(name)
        print(f"{name}={installed}; expected={version}", flush=True)
        if installed != version:
            return 1
    import paddle
    import paddleocr
    print("OCR imports passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
