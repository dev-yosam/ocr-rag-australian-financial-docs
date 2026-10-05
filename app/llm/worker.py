"""Offline, single-request Qwen subprocess. Never serves an HTTP endpoint."""
import os
from pathlib import Path
import sys
import time

from app.core.config import ROOT, local_runtime
from app.core.files import contained, read_json, write_json
from app.llm.models import verify_model
from app.llm.runtime import activate_device, check_packages


def deny_network(event: str, args: tuple) -> None:
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("Network disabled during LLM extraction")


def offline_runtime(root: Path) -> None:
    local_runtime(root)
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "HF_HUB_DISABLE_IMPLICIT_TOKEN", "DO_NOT_TRACK"):
        os.environ[name] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    sys.addaudithook(deny_network)


class GenerationProgress:
    """Transformers streamer that saves counters only, never partial text."""
    def __init__(self, target: Path, payload: dict):
        self.target, self.payload = target, payload
        self.prompt_pending = True
        self.count = 0
        self.started = self.saved = time.monotonic()

    def put(self, value) -> None:
        if self.prompt_pending:
            self.prompt_pending = False  # generate() sends prompt IDs first.
            return
        self.count += value.numel()  # One request, no batching or beams.
        if self.count == 1 or time.monotonic() - self.saved >= 10:
            self.end()

    def end(self) -> None:
        self.saved = time.monotonic()
        self.payload.update(output_tokens=self.count,
                            generation_seconds=round(self.saved - self.started, 3))
        write_json(self.target, self.payload)


def run(request: dict, target: Path) -> int:
    payload = {"status": "initializing", "stage": "runtime_setup", "versions": {}}
    write_json(target, payload)
    offline_runtime(ROOT)
    payload["versions"] = check_packages()
    payload["stage"] = "device_preflight"
    write_json(target, payload)
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    device, dtype = activate_device(torch, request["device"], request["dtype"], request["threads"])
    payload.update(device=request["device"], dtype=dtype, stage="model_checksums")
    write_json(target, payload)
    directory, identity = verify_model(ROOT)
    payload.update(model=identity, stage="tokenizing")
    write_json(target, payload)
    tokenizer = AutoTokenizer.from_pretrained(str(directory), local_files_only=True, trust_remote_code=False)
    prompt = tokenizer.apply_chat_template(request["messages"], tokenize=False, add_generation_prompt=True,
                                           enable_thinking=False)
    inputs = tokenizer(prompt, return_tensors="pt", add_special_tokens=False, truncation=False)
    count = inputs["input_ids"].shape[-1]
    payload["input_tokens"] = count
    if count > request["max_input_tokens"]:
        payload.update(status="failed", stage="context_limit", error_type="InputTokenLimit")
        write_json(target, payload)
        return 1  # Never silently truncate the document or field instructions.
    payload["stage"] = "model_loading"
    write_json(target, payload)
    model = AutoModelForCausalLM.from_pretrained(
        str(directory), local_files_only=True, trust_remote_code=False, use_safetensors=True,
        torch_dtype=getattr(torch, dtype), attn_implementation="eager",
    ).to(device).eval()
    inputs = {key: tensor.to(device) for key, tensor in inputs.items()}
    payload.update(stage="generating", output_tokens=0)
    write_json(target, payload)
    started = time.monotonic()
    progress = GenerationProgress(target, payload)
    with torch.inference_mode():
        result = model.generate(**inputs, max_new_tokens=request["max_new_tokens"], do_sample=False,
                                use_cache=True, pad_token_id=tokenizer.eos_token_id, streamer=progress)
    generated = result[0, count:]
    payload.update(text=tokenizer.decode(generated, skip_special_tokens=True),
                   output_tokens=len(generated), generation_seconds=round(time.monotonic() - started, 3))
    eos = model.generation_config.eos_token_id
    eos_ids = eos if isinstance(eos, list) else [eos]
    if len(generated) == 0 or int(generated[-1]) not in eos_ids:
        payload.update(status="failed", stage="output_limit", error_type="IncompleteGeneration")
    else:
        payload.update(status="completed", stage="completed")
    write_json(target, payload)
    return 0 if payload["status"] == "completed" else 1


def main() -> int:
    request_path = contained(ROOT, sys.argv[1])
    target = contained(ROOT, sys.argv[2], must_exist=False)
    try:
        return run(read_json(request_path), target)
    except Exception as error:
        payload = read_json(target) if target.exists() else {}
        payload.update(status="failed", error_type=type(error).__name__)
        write_json(target, payload)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
