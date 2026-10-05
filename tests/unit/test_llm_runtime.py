"""SYNTHETIC mocked runtime contracts; no torch import or real GPU/model use."""
from contextlib import nullcontext
from importlib.metadata import PackageNotFoundError
import os
import sys
from types import SimpleNamespace

import pytest

from app.core.errors import ExtractionError, InputError
from app.core.files import read_json, write_json
from app.llm import runtime, worker


def fake_torch(*, available=True, count=2, cuda_version="12.6", bf16=True, broken=False):
    calls = []

    class Tensor:
        def __matmul__(self, other):
            if broken:
                raise RuntimeError("SYNTHETIC PRIVATE PROVIDER ERROR")
            return self

        def float(self):
            return self

        def sum(self):
            return self

        def item(self):
            return 8

    def query(name, value):
        calls.append((name, value))
        return value

    def ones(shape, **kwargs):
        calls.append(("ones", shape, kwargs))
        return Tensor()

    torch = SimpleNamespace(
        set_num_threads=lambda value: calls.append(("threads", value)),
        cuda=SimpleNamespace(
            is_available=lambda: query("cuda_available", available),
            device_count=lambda: query("cuda_count", count),
            set_device=lambda value: calls.append(("cuda_selected", value)),
            is_bf16_supported=lambda *, including_emulation: query("bf16_supported", bf16 and not including_emulation),
        ),
        version=SimpleNamespace(cuda=cuda_version),
        float32="FAKE_FLOAT32", float16="FAKE_FLOAT16", bfloat16="FAKE_BFLOAT16",
        ones=ones, inference_mode=nullcontext,
    )
    return torch, calls


@pytest.mark.parametrize("torch_version", ["2.8.0+cpu", "2.8.0+cu126"])
def test_pinned_supported_packages(monkeypatch, torch_version):
    versions = {"torch": torch_version, "transformers": "4.57.6", "tokenizers": "0.22.2", "safetensors": "0.8.0"}
    monkeypatch.setattr(runtime, "version", versions.__getitem__)
    assert runtime.check_packages() == versions


@pytest.mark.parametrize("package,value", [("torch", "2.8.0+cu129"), ("torch", "2.9.0+cpu"), ("transformers", "4.56.0"), ("tokenizers", None)])
def test_package_preflight_rejects_wrong_or_missing_runtime(monkeypatch, package, value):
    versions = {"torch": "2.8.0+cpu", "transformers": "4.57.6", "tokenizers": "0.22.2", "safetensors": "0.8.0"}
    versions[package] = value

    def installed(name):
        if versions[name] is None:
            raise PackageNotFoundError("SYNTHETIC PRIVATE INSTALL DETAILS")
        return versions[name]

    monkeypatch.setattr(runtime, "version", installed)
    with pytest.raises(ExtractionError) as caught:
        runtime.check_packages()
    assert "PRIVATE" not in str(caught.value)


def test_cpu_does_not_query_cuda_and_auto_is_float32():
    torch, calls = fake_torch(available=False, count=0, cuda_version=None)
    assert runtime.activate_device(torch, "cpu", "auto", 2) == ("cpu", "float32")
    assert calls == [("threads", 2), ("ones", (2, 2), {"device": "cpu", "dtype": "FAKE_FLOAT32"})]


def test_gpu_auto_float16_uses_requested_visible_index():
    torch, calls = fake_torch()
    assert runtime.activate_device(torch, "gpu:1", "auto", 4) == ("cuda:1", "float16")
    assert ("cuda_selected", 1) in calls
    assert ("ones", (2, 2), {"device": "cuda:1", "dtype": "FAKE_FLOAT16"}) in calls


@pytest.mark.parametrize("options,device", [
    ({"available": False}, "gpu:0"), ({"count": 0}, "gpu:0"),
    ({"count": 1}, "gpu:1"), ({"cuda_version": "12.9"}, "gpu:0"),
])
def test_unavailable_or_wrong_cuda_never_falls_back(options, device):
    torch, calls = fake_torch(**options)
    with pytest.raises(ExtractionError):
        runtime.activate_device(torch, device, "auto", 2)
    assert not any(call[0] == "ones" for call in calls)


def test_bfloat16_rejected_before_allocation_on_unsupported_gpu():
    torch, calls = fake_torch(bf16=False)
    with pytest.raises(ExtractionError, match="bfloat16"):
        runtime.activate_device(torch, "gpu:0", "bfloat16", 2)
    assert not any(call[0] == "ones" for call in calls)


@pytest.mark.parametrize("dtype", ["float32", "float16", "bfloat16"])
def test_supported_explicit_gpu_dtype(dtype):
    torch, calls = fake_torch()
    assert runtime.activate_device(torch, "gpu:0", dtype, 2) == ("cuda:0", dtype)
    assert calls[-1][2]["dtype"] == getattr(torch, dtype)


@pytest.mark.parametrize("device", ["auto", "gpu", "gpu:-1", "gpu:01", "cuda:0"])
def test_invalid_device_rejected_before_runtime_calls(device):
    torch, calls = fake_torch()
    with pytest.raises(InputError):
        runtime.activate_device(torch, device, "auto", 2)
    assert calls == []


def test_unknown_dtype_and_provider_errors_sanitized():
    torch, calls = fake_torch()
    with pytest.raises(ExtractionError, match="dtype"):
        runtime.activate_device(torch, "cpu", "int4", 2)
    assert not any(call[0] == "ones" for call in calls)
    torch, _ = fake_torch(broken=True)
    with pytest.raises(ExtractionError) as caught:
        runtime.activate_device(torch, "cpu", "auto", 2)
    assert "PRIVATE" not in str(caught.value)


def fake_generation(repo, monkeypatch, *, count=5, generated=(7, 2), eos=2):
    calls = {}
    torch, torch_calls = fake_torch()
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(worker, "ROOT", repo)
    monkeypatch.setattr(worker, "offline_runtime", lambda root: calls.update(offline_root=root))
    monkeypatch.setattr(worker, "check_packages", lambda: {"runtime": "FAKE"})
    monkeypatch.setattr(worker, "verify_model", lambda root: (repo / "FAKE_WEIGHTS", {"repository": "FAKE", "revision": "FAKE"}))

    class InputTensor:
        shape = (1, count)

        def to(self, device):
            calls.setdefault("input_devices", []).append(device)
            return self

    class Tokenizer:
        eos_token_id = 2

        def apply_chat_template(self, messages, **kwargs):
            calls["template"] = (messages, kwargs)
            return "SYNTHETIC TOKENIZED PROMPT"

        def __call__(self, prompt, **kwargs):
            calls["tokenize"] = (prompt, kwargs)
            return {"input_ids": InputTensor(), "attention_mask": InputTensor()}

        def decode(self, tokens, **kwargs):
            calls["decode"] = (tokens, kwargs)
            return "SYNTHETIC GENERATED RESPONSE"

    class Generated:
        def __getitem__(self, index):
            assert index == (0, slice(count, None))
            return list(generated)

    class Model:
        generation_config = SimpleNamespace(eos_token_id=eos)

        def to(self, device):
            calls["model_device"] = device
            return self

        def eval(self):
            calls["eval"] = True
            return self

        def generate(self, **kwargs):
            calls["generate"] = kwargs
            return Generated()

    def load_tokenizer(path, **kwargs):
        calls["load_tokenizer"] = (path, kwargs)
        return Tokenizer()

    def load_model(path, **kwargs):
        calls["load_model"] = (path, kwargs)
        return Model()

    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=load_tokenizer),
        AutoModelForCausalLM=SimpleNamespace(from_pretrained=load_model),
    ))
    request = {"device": "cpu", "dtype": "auto", "threads": 2,
               "messages": [{"role": "user", "content": "SYNTHETIC OCR"}],
               "max_input_tokens": 5, "max_new_tokens": 128}
    return request, repo / "worker-result.json", calls, torch_calls


def test_context_limit_refuses_truncation_or_model_loading(repo, monkeypatch):
    request, target, calls, _ = fake_generation(repo, monkeypatch, count=6)
    assert worker.run(request, target) == 1
    assert calls["tokenize"][1]["truncation"] is False
    assert "load_model" not in calls and "generate" not in calls
    payload = read_json(target)
    assert payload["status"] == "failed"
    assert payload["stage"] == "context_limit"
    assert payload["error_type"] == "InputTokenLimit"
    assert payload["input_tokens"] == 6


def test_offline_loading_and_greedy_generation_contract(repo, monkeypatch):
    request, target, calls, _ = fake_generation(repo, monkeypatch)
    assert worker.run(request, target) == 0  # Exactly at input limit is allowed.
    assert calls["offline_root"] == repo
    assert calls["template"][0] == request["messages"]
    assert calls["template"][1] == {"tokenize": False, "add_generation_prompt": True, "enable_thinking": False}
    assert calls["load_tokenizer"][1] == {"local_files_only": True, "trust_remote_code": False}
    assert calls["load_model"][1] == {"local_files_only": True, "trust_remote_code": False,
                                        "use_safetensors": True, "torch_dtype": "FAKE_FLOAT32", "attn_implementation": "eager"}
    assert calls["model_device"] == "cpu" and calls["input_devices"] == ["cpu", "cpu"]
    assert calls["generate"]["do_sample"] is False
    assert calls["generate"]["max_new_tokens"] == 128
    assert calls["decode"] == ([7, 2], {"skip_special_tokens": True})
    payload = read_json(target)
    assert payload["status"] == "completed" and payload["output_tokens"] == 2
    assert payload["dtype"] == "float32" and payload["text"] == "SYNTHETIC GENERATED RESPONSE"


@pytest.mark.parametrize("generated", [(), (7,), (7, 8)])
def test_missing_eos_retains_text_but_fails_generation(repo, monkeypatch, generated):
    request, target, _, _ = fake_generation(repo, monkeypatch, generated=generated)
    assert worker.run(request, target) == 1
    payload = read_json(target)
    assert payload["status"] == "failed"
    assert payload["stage"] == "output_limit"
    assert payload["error_type"] == "IncompleteGeneration"
    assert payload["text"] == "SYNTHETIC GENERATED RESPONSE"


def test_multiple_eos_ids_are_accepted(repo, monkeypatch):
    request, target, _, _ = fake_generation(repo, monkeypatch, generated=(7, 3), eos=[2, 3])
    assert worker.run(request, target) == 0


def test_offline_flags_and_audit_hook(monkeypatch, repo):
    calls = []
    monkeypatch.setattr(worker, "local_runtime", lambda root: calls.append(root))
    monkeypatch.setattr(sys, "addaudithook", lambda hook: calls.append(hook))
    names = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY",
             "HF_HUB_DISABLE_IMPLICIT_TOKEN", "DO_NOT_TRACK", "TOKENIZERS_PARALLELISM")
    for name in names:
        monkeypatch.setenv(name, "SYNTHETIC_TEST_PRIOR_VALUE")
    worker.offline_runtime(repo)
    assert calls == [repo, worker.deny_network]
    assert all(os.environ[name] == "1" for name in names[:-1])
    assert os.environ["TOKENIZERS_PARALLELISM"] == "false"
    for event in ("socket.connect", "socket.getaddrinfo", "socket.sendto"):
        with pytest.raises(RuntimeError, match="Network disabled"):
            worker.deny_network(event, ())
    worker.deny_network("open", ())


def test_worker_exception_is_recorded_without_private_details(repo, monkeypatch):
    request = repo / "request.json"
    target = repo / "response.json"
    write_json(request, {})
    monkeypatch.setattr(worker, "ROOT", repo)
    monkeypatch.setattr(sys, "argv", ["worker", request.name, target.name])

    def broken(request, target):
        write_json(target, {"status": "initializing", "stage": "model_loading"})
        raise RuntimeError("SYNTHETIC PRIVATE DOCUMENT DETAILS")

    monkeypatch.setattr(worker, "run", broken)
    assert worker.main() == 1
    payload = read_json(target)
    assert payload == {"status": "failed", "stage": "model_loading", "error_type": "RuntimeError"}


def test_progress_records_counts_without_prompt_or_generated_text(repo):
    target = repo / "progress.json"
    progress = worker.GenerationProgress(target, {"status": "initializing", "stage": "generating"})
    progress.put(SimpleNamespace(numel=lambda: 1000))  # Fake prompt, excluded.
    assert not target.exists()
    progress.put(SimpleNamespace(numel=lambda: 1))
    assert read_json(target)["output_tokens"] == 1
    progress.put(SimpleNamespace(numel=lambda: 1))
    progress.end()
    payload = read_json(target)
    assert payload["output_tokens"] == 2
    assert set(payload) == {"status", "stage", "output_tokens", "generation_seconds"}
