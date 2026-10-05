from dataclasses import dataclass
import os
import re
from pathlib import Path

from app.core.errors import InputError

ROOT = Path(__file__).resolve().parents[2]


def validate_device(device: str) -> None:
    if not isinstance(device, str) or re.fullmatch(r"cpu|gpu:(0|[1-9][0-9]*)", device) is None:
        raise InputError("Device must be cpu or gpu:<non-negative index>")


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    device: str = "cpu"
    ragflow_base_url: str = ""
    ragflow_api_key: str = ""
    ragflow_dataset_id: str = ""
    ragflow_timeout: float = 30.0
    ocr_timeout: float = 1800.0
    extractor: str = "rules"
    llm_device: str = "cpu"
    llm_python: str = ""
    llm_timeout: float = 1800.0
    llm_max_input_tokens: int = 8192
    llm_max_new_tokens: int = 2048
    llm_threads: int = 4
    llm_dtype: str = "auto"

    def __post_init__(self) -> None:
        validate_device(self.device)
        validate_device(self.llm_device)
        if self.extractor not in {"rules", "llm"}:
            raise InputError("Extractor must be rules or llm")
        if not 1 <= self.llm_timeout <= 14400:
            raise InputError("Invalid LLM timeout configuration")
        if not 256 <= self.llm_max_input_tokens <= 16384 or not 128 <= self.llm_max_new_tokens <= 4096:
            raise InputError("Invalid LLM token limits")
        if not 1 <= self.llm_threads <= 64 or self.llm_dtype not in {"auto", "float32", "float16", "bfloat16"}:
            raise InputError("Invalid LLM runtime configuration")

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
        try:
            llm_values = {
                "llm_timeout": float(os.environ.get("LLM_TIMEOUT_SECONDS") or "1800"),
                "llm_max_input_tokens": int(os.environ.get("LLM_MAX_INPUT_TOKENS") or "8192"),
                "llm_max_new_tokens": int(os.environ.get("LLM_MAX_NEW_TOKENS") or "2048"),
                "llm_threads": int(os.environ.get("LLM_CPU_THREADS") or "4"),
            }
        except ValueError:
            raise InputError("Invalid LLM runtime configuration") from None
        return cls(
            device=device,
            extractor=os.environ.get("INVOICE_EXTRACTOR") or "rules",
            llm_device=os.environ.get("LLM_DEVICE") or device,
            llm_python=os.environ.get("LLM_PYTHON") or "",
            llm_dtype=os.environ.get("LLM_DTYPE") or "auto",
            **llm_values,
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
        "TORCH_HOME": ".cache/torch",
        "TORCHINDUCTOR_CACHE_DIR": ".cache/torchinductor",
        "TEMP": ".runtime/tmp",
        "TMP": ".runtime/tmp",
        "TMPDIR": ".runtime/tmp",
    }.items():
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()):
            raise InputError("Runtime directory escapes repository")
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path.resolve())
