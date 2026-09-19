"""Explicit device selection and sanitized checks; never fall back to another device."""
import importlib.metadata

from app.core.config import validate_device
from app.core.errors import ParserError


class RuntimeConfigurationError(ParserError):
    pass


def check_packages(device: str) -> dict[str, str]:
    validate_device(device)
    runtime = "paddlepaddle" if device == "cpu" else "paddlepaddle-gpu"
    other = "paddlepaddle-gpu" if device == "cpu" else "paddlepaddle"
    try:
        importlib.metadata.version(other)
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise RuntimeConfigurationError("Wrong or mixed Paddle runtime; use a separate environment for this device")
    expected = {"paddleocr": "3.6.0", "paddlex": "3.6.0", runtime: "3.2.1"}
    try:
        versions = {name: importlib.metadata.version(name) for name in expected}
    except importlib.metadata.PackageNotFoundError:
        raise RuntimeConfigurationError("Required OCR package missing for selected device") from None
    if versions != expected:
        raise RuntimeConfigurationError("OCR dependency version mismatch")
    return versions


def activate_device(device: str) -> str:
    validate_device(device)
    try:
        import paddle
        if device != "cpu":
            if not paddle.is_compiled_with_cuda():
                raise RuntimeConfigurationError("Selected GPU requires a CUDA-enabled Paddle runtime")
            if int(device.split(":")[1]) >= paddle.device.cuda.device_count():
                raise RuntimeConfigurationError("Selected GPU is unavailable; check allocation and visible devices")
        paddle.set_device(device)
        actual = paddle.get_device()
        if actual != device:
            raise RuntimeConfigurationError("Paddle did not activate the requested device")
        # Force allocation and execution so missing drivers/kernels fail before OCR.
        result = (paddle.to_tensor([1.0]) + 1.0).numpy()
        if result.tolist() != [2.0]:
            raise RuntimeConfigurationError("Device computation check failed")
        return actual
    except RuntimeConfigurationError:
        raise
    except Exception:
        raise RuntimeConfigurationError("Selected device could not execute; check runtime and driver compatibility") from None
