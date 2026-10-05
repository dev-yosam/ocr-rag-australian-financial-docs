"""Pinned public model preparation and strictly offline integrity verification."""
from collections.abc import Callable
import json
from pathlib import Path
import re
import urllib.request

from app.core.errors import InputError
from app.core.files import contained, sha256, write_json

MODEL_REPOSITORY = "Qwen/Qwen3-4B-Instruct-2507"
MODEL_PATH = ".models/llm/Qwen3-4B-Instruct-2507"
LOCK_PATH = "requirements/llm-model.lock.json"
WEIGHT_FILES = tuple(f"model-{index:05d}-of-00003.safetensors" for index in range(1, 4))
MODEL_FILES = frozenset((
    "LICENSE", "config.json", "generation_config.json", "merges.txt",
    "model.safetensors.index.json", "tokenizer.json", "tokenizer_config.json",
    "vocab.json", *WEIGHT_FILES,
))


def _read_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (OSError, ValueError, UnicodeError):
        raise InputError("Invalid LLM model metadata") from None


def _lock(root: Path) -> tuple[dict, str]:
    path = contained(root, LOCK_PATH)
    data = _read_object(path)
    if (set(data) != {"schema_version", "repository", "revision", "files"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or data["repository"] != MODEL_REPOSITORY
            or not isinstance(data["revision"], str)
            or re.fullmatch(r"[0-9a-f]{40}", data["revision"]) is None
            or not isinstance(data["files"], dict)
            or set(data["files"]) != MODEL_FILES):
        raise InputError("Invalid LLM model lock")
    for metadata in data["files"].values():
        if (not isinstance(metadata, dict)
                or set(metadata) != {"sha256", "size"}
                or not isinstance(metadata["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", metadata["sha256"]) is None
                or type(metadata["size"]) is not int or metadata["size"] <= 0):
            raise InputError("Invalid LLM model lock")
    return data, sha256(path)


def _file(root: Path, directory: Path, name: str) -> Path:
    # Both repository and model-directory boundaries apply, including symlinks.
    path = contained(root, f"{MODEL_PATH}/{name}", must_exist=False)
    if not path.is_relative_to(directory):
        raise InputError("LLM model file escapes its directory")
    return path


def _verify_file(path: Path, expected: dict) -> None:
    try:
        if (not path.is_file() or path.stat().st_size != expected["size"]
                or sha256(path) != expected["sha256"]):
            raise ValueError
    except (OSError, ValueError):
        raise InputError(
            "LLM model file missing or checksum mismatch; inspect the model cache "
            "and explicitly prepare the model again"
        ) from None


def _manifest(lock: dict, lock_digest: str) -> dict:
    return {**lock, "path": MODEL_PATH, "lock_sha256": lock_digest}


def _verify_content(root: Path, directory: Path, lock: dict) -> None:
    allowed = MODEL_FILES | {"manifest.json"}
    if not directory.is_dir():
        raise InputError("LLM model is missing; run scripts/prepare_llm.py first")
    if any(item.name not in allowed or not item.is_file() for item in directory.iterdir()):
        raise InputError("Unexpected LLM model cache file; inspect the cache before continuing")
    for name, expected in lock["files"].items():
        _verify_file(_file(root, directory, name), expected)
    # The pinned model must load through built-in Transformers implementations.
    config = _read_object(_file(root, directory, "config.json"))
    tokenizer_config = _read_object(_file(root, directory, "tokenizer_config.json"))
    if config.get("model_type") != "qwen3" or "auto_map" in config or "auto_map" in tokenizer_config:
        raise InputError("Unsupported LLM model configuration")
    index = _read_object(_file(root, directory, "model.safetensors.index.json"))
    weights = index.get("weight_map")
    if (not isinstance(weights, dict) or not weights
            or any(not isinstance(value, str) for value in weights.values())
            or set(weights.values()) != set(WEIGHT_FILES)):
        raise InputError("Invalid LLM safetensors shard index")


def verify_model(root: Path) -> tuple[Path, dict]:
    """Verify local files against the checked-in lock; never contact a provider."""
    try:
        lock, lock_digest = _lock(root)
        directory = contained(root, MODEL_PATH, must_exist=False)
        manifest_path = _file(root, directory, "manifest.json")
        if not manifest_path.is_file():
            raise InputError("LLM model is not prepared; run scripts/prepare_llm.py first")
        if _read_object(manifest_path) != _manifest(lock, lock_digest):
            raise InputError("LLM model manifest does not match the pinned lock")
        _verify_content(root, directory, lock)
        return directory, {
            "repository": lock["repository"], "revision": lock["revision"],
            "lock_sha256": lock_digest,
        }
    except OSError:
        raise InputError("Cannot verify the local LLM model cache") from None


def model_directory(root: Path) -> Path:
    return verify_model(root)[0]


def model_identity(root: Path) -> dict:
    return verify_model(root)[1]


def _download(url: str, destination: Path) -> None:
    # No Hugging Face SDK, credential file, token, or authenticated proxy lookup.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=120) as response, destination.open("xb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    except Exception:
        raise InputError(
            "LLM model download failed; remove only the incomplete .download file "
            "before retrying explicit preparation"
        ) from None


def prepare_model(root: Path, *, verify_only: bool = False,
                  progress: Callable[[str], None] | None = None) -> tuple[Path, dict]:
    """Explicit installation step. Existing complete models are verified offline."""
    try:
        lock, lock_digest = _lock(root)
        directory = contained(root, MODEL_PATH, must_exist=False)
        manifest_path = _file(root, directory, "manifest.json")
        if verify_only or manifest_path.exists():
            return verify_model(root)
        directory.mkdir(parents=True, exist_ok=True)
        for name, expected in lock["files"].items():
            target = _file(root, directory, name)
            partial = _file(root, directory, name + ".download")
            if target.exists():
                # Do not silently replace a corrupted existing model or config.
                _verify_file(target, expected)
            else:
                if partial.exists():
                    raise InputError(
                        "Incomplete LLM model download exists; remove only the "
                        ".download file before retrying explicit preparation"
                    )
                url = f"https://huggingface.co/{lock['repository']}/resolve/{lock['revision']}/{name}"
                if progress:
                    progress(f"Downloading {name}")
                _download(url, partial)
                _verify_file(partial, expected)
                partial.replace(target)
            if progress:
                progress(f"Verified {name}")
        _verify_content(root, directory, lock)
        _file(root, directory, "manifest.json.tmp")  # Validate atomic-write target too.
        write_json(manifest_path, _manifest(lock, lock_digest))
        return directory, {
            "repository": lock["repository"], "revision": lock["revision"],
            "lock_sha256": lock_digest,
        }
    except OSError:
        raise InputError("Cannot prepare the local LLM model cache") from None
