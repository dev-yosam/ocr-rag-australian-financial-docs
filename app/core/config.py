from dataclasses import dataclass
import os
from pathlib import Path

from app.core.errors import InputError

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    device: str = "cpu"
    ragflow_base_url: str = ""
    ragflow_api_key: str = ""
    ragflow_dataset_id: str = ""
    ragflow_timeout: float = 30.0
    ocr_timeout: float = 1800.0

    @classmethod
    def from_env(cls) -> "Settings":
        # Read only named application variables; never dump environment/config.
        try:
            timeout = float(os.environ.get("RAGFLOW_TIMEOUT_SECONDS") or "30")
            if not 0 < timeout <= 300:
                raise ValueError
        except ValueError:
            raise InputError("Invalid RAGFlow timeout configuration") from None
        try:
            ocr_timeout = float(os.environ.get("PADDLEOCR_TIMEOUT_SECONDS") or "1800")
            if not 1 <= ocr_timeout <= 3600:
                raise ValueError
        except ValueError:
            raise InputError("Invalid OCR timeout configuration") from None
        device = os.environ.get("PADDLEOCR_DEVICE") or "cpu"
        if device != "cpu" and not device.startswith("gpu:"):
            raise InputError("Device must be cpu or gpu:<index>")
        return cls(
            device=device,
            ragflow_base_url=os.environ.get("RAGFLOW_BASE_URL", ""),
            ragflow_api_key=os.environ.get("RAGFLOW_API_KEY", ""),
            ragflow_dataset_id=os.environ.get("RAGFLOW_DATASET_ID", ""),
            ragflow_timeout=timeout,
            ocr_timeout=ocr_timeout,
        )


def local_runtime(root: Path) -> None:
    """Set only dependency cache locations, before importing heavy libraries."""
    for name, relative in {
        "PADDLE_PDX_CACHE_HOME": ".cache/paddlex",
        "HF_HOME": ".cache/huggingface",
        "MODELSCOPE_CACHE": ".cache/modelscope",
        "PADDLE_HOME": ".cache/paddle",
        "XDG_CACHE_HOME": ".cache",
        "TEMP": ".runtime/tmp",
        "TMP": ".runtime/tmp",
        "TMPDIR": ".runtime/tmp",
    }.items():
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()):
            raise InputError("Runtime directory escapes repository")
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path.resolve())
