"""Explicit CPU/CUDA selection. Importing this module does not import PyTorch."""
from importlib.metadata import version

from app.core.config import validate_device
from app.core.errors import ExtractionError


def check_packages() -> dict[str, str]:
    try:
        versions = {name: version(name) for name in ("torch", "transformers", "tokenizers", "safetensors")}
        if versions["torch"] not in {"2.8.0+cpu", "2.8.0+cu126"} or versions["transformers"] != "4.57.6":
            raise ValueError
        return versions
    except Exception:
        raise ExtractionError("LLM runtime missing or differs from the pinned requirements") from None


def activate_device(torch, device: str, dtype: str, threads: int) -> tuple[str, str]:
    validate_device(device)
    torch.set_num_threads(threads)
    selected = "cpu"
    if device.startswith("gpu:"):
        index = int(device.split(":")[1])
        if not torch.cuda.is_available() or index >= torch.cuda.device_count():
            raise ExtractionError("Requested LLM GPU is unavailable; no CPU fallback")
        if torch.version.cuda != "12.6":
            raise ExtractionError("Install the pinned CUDA 12.6 LLM runtime")
        selected = f"cuda:{index}"
        torch.cuda.set_device(index)
    resolved_dtype = ("float32" if selected == "cpu" else "float16") if dtype == "auto" else dtype
    if resolved_dtype not in {"float32", "float16", "bfloat16"}:
        raise ExtractionError("Unsupported LLM dtype")
    if (selected.startswith("cuda") and resolved_dtype == "bfloat16"
            and not torch.cuda.is_bf16_supported(including_emulation=False)):
        raise ExtractionError("Requested GPU does not support bfloat16")
    try:
        tensor = torch.ones((2, 2), device=selected, dtype=getattr(torch, resolved_dtype))
        if (tensor @ tensor).float().sum().item() != 8:
            raise ValueError
    except Exception:
        raise ExtractionError("LLM device computation failed") from None
    return selected, resolved_dtype
