"""Fake runtime contracts; these tests do not prove actual GPU inference."""
import sys
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.errors import InputError
from app.paddleocr import runtime


@pytest.mark.parametrize("device", ["cpu", "gpu:0", "gpu:2"])
def test_device_selection(monkeypatch, device):
    monkeypatch.setenv("PADDLEOCR_DEVICE", device)
    assert Settings.from_env().device == device


def test_default_cpu(monkeypatch):
    monkeypatch.delenv("PADDLEOCR_DEVICE", raising=False)
    assert Settings.from_env().device == "cpu"
    assert Settings().device == "cpu"


@pytest.mark.parametrize("device", ["gpu", "gpu:", "gpu:-1", "gpu:1,2", "gpu:01", "gpu:a", "CPU", "cpu ", "auto", "gpu:0\n"])
def test_invalid_device(monkeypatch, device):
    monkeypatch.setenv("PADDLEOCR_DEVICE", device)
    with pytest.raises(InputError):
        Settings.from_env()
    with pytest.raises(InputError):
        Settings(device=device)


def packages(monkeypatch, installed):
    def version(name):
        if name not in installed:
            raise runtime.importlib.metadata.PackageNotFoundError(name)
        return installed[name]
    monkeypatch.setattr(runtime.importlib.metadata, "version", version)


@pytest.mark.parametrize("device,package", [("cpu", "paddlepaddle"), ("gpu:0", "paddlepaddle-gpu")])
def test_matching_runtime(monkeypatch, device, package):
    installed = {"paddleocr": "3.6.0", "paddlex": "3.6.0", package: "3.2.1"}
    packages(monkeypatch, installed)
    assert runtime.check_packages(device) == installed


@pytest.mark.parametrize("installed", [
    {}, {"paddlepaddle-gpu": "3.2.1"},
    {"paddlepaddle": "3.2.1", "paddlepaddle-gpu": "3.2.1"},
    {"paddleocr": "3.7.0", "paddlex": "3.6.0", "paddlepaddle": "3.2.1"},
])
def test_missing_wrong_mixed_packages(monkeypatch, installed):
    packages(monkeypatch, installed)
    with pytest.raises(runtime.RuntimeConfigurationError):
        runtime.check_packages("cpu")


def fake_paddle(monkeypatch, cuda=True, count=1, actual=None, broken=False):
    calls = []
    class Tensor:
        def __add__(self, other):
            if broken:
                raise RuntimeError("FAKE PRIVATE PROVIDER DETAILS")
            return self
        def numpy(self):
            return SimpleNamespace(tolist=lambda: [2.0])
    def set_device(device):
        calls.append(device)
    paddle = SimpleNamespace(
        is_compiled_with_cuda=lambda: cuda,
        device=SimpleNamespace(cuda=SimpleNamespace(device_count=lambda: count)),
        set_device=set_device, get_device=lambda: actual or calls[-1],
        to_tensor=lambda value: Tensor())
    monkeypatch.setitem(sys.modules, "paddle", paddle)
    return calls


@pytest.mark.parametrize("device", ["cpu", "gpu:0", "gpu:1"])
def test_activate_and_execute(monkeypatch, device):
    calls = fake_paddle(monkeypatch, count=2)
    assert runtime.activate_device(device) == device
    assert calls == [device]


@pytest.mark.parametrize("cuda,count,device", [(False, 1, "gpu:0"), (True, 0, "gpu:0"), (True, 1, "gpu:1")])
def test_unavailable_gpu_never_falls_back(monkeypatch, cuda, count, device):
    calls = fake_paddle(monkeypatch, cuda=cuda, count=count)
    with pytest.raises(runtime.RuntimeConfigurationError):
        runtime.activate_device(device)
    assert calls == []


def test_cpu_works_without_cuda(monkeypatch):
    fake_paddle(monkeypatch, cuda=False, count=0)
    assert runtime.activate_device("cpu") == "cpu"


def test_no_silent_device_substitution(monkeypatch):
    fake_paddle(monkeypatch, actual="cpu")
    with pytest.raises(runtime.RuntimeConfigurationError):
        runtime.activate_device("gpu:0")


def test_driver_failure_sanitized(monkeypatch):
    fake_paddle(monkeypatch, broken=True)
    with pytest.raises(runtime.RuntimeConfigurationError) as error:
        runtime.activate_device("gpu:0")
    assert "PRIVATE" not in str(error.value)


def test_worker_stops_before_models_on_bad_runtime(repo, monkeypatch):
    from app.paddleocr import worker
    monkeypatch.setattr(worker, "ROOT", repo)
    monkeypatch.setattr(sys, "addaudithook", lambda hook: None)
    monkeypatch.setattr(sys, "argv", ["worker", "fake.png", str(repo / "result.json"), "gpu:0"])
    def reject(device):
        raise runtime.RuntimeConfigurationError("Required OCR package missing for selected device")
    monkeypatch.setattr(worker, "check_packages", reject)
    monkeypatch.setattr(worker, "model_directories", lambda root: pytest.fail("Must not load models"))
    with pytest.raises(runtime.RuntimeConfigurationError):
        worker.main()
    from app.core.files import read_json
    assert read_json(repo / "result.json")["stage"] == "device_preflight"
