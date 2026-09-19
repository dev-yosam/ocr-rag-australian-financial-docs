"""Content-free OCR import preflight, without contacting model providers."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import ROOT, Settings, local_runtime
from app.paddleocr.worker import deny_network
from app.paddleocr.runtime import check_packages, activate_device
from app.core.errors import PipelineError


def main() -> int:
    local_runtime(ROOT)
    sys.addaudithook(deny_network)
    try:
        device = Settings.from_env().device
        versions = check_packages(device)
        actual = activate_device(device)
    except PipelineError as error:
        print(str(error), flush=True)
        return 1
    for name, version in versions.items():
        print(f"{name}={version}", flush=True)
    print(f"Device computation passed: {actual}", flush=True)
    import paddleocr
    print("OCR imports passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
