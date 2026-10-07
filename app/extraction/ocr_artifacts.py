"""Read and verify saved OCR; never modify source artifacts."""
import hashlib
from pathlib import Path
import re

from app.core.errors import InputError
from app.core.files import contained, read_json, sha256

MAX_ARTIFACT_BYTES = 32_000_000


def load_ocr(root: Path, directory: str) -> tuple[dict, dict[str, bytes], str]:
    previous = contained(root, directory)
    outputs = contained(root, "outputs")
    if previous == outputs or not previous.is_relative_to(outputs) or not previous.is_dir():
        raise InputError("Select a saved run under outputs")
    manifest_path = contained(root, f"{directory}/manifest.json")
    manifest_hash = sha256(manifest_path)
    prior = read_json(manifest_path)
    if not isinstance(prior, dict) or not isinstance(prior.get("artifacts"), dict):
        raise InputError("Invalid OCR manifest")
    if prior.get("ocr_status", prior.get("status")) not in ("completed", "completed_needs_review"):
        raise InputError("OCR run is not complete")
    if not isinstance(prior.get("source"), str) or not isinstance(prior.get("versions"), dict):
        raise InputError("Missing OCR provenance")
    if not isinstance(prior.get("source_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", prior["source_sha256"]):
        raise InputError("Missing source hash")
    source = contained(root, prior["source"], must_exist=False)
    # Original image need not be present to replay downloaded Cetus artifacts.
    if source.exists() and (not source.is_file() or sha256(source) != prior["source_sha256"]):
        raise InputError("Source file no longer matches OCR provenance")
    snapshots = {}
    for name in ("raw.json", "parsed.md"):
        path = contained(root, f"{directory}/{name}")
        if not path.is_file() or path.stat().st_size > MAX_ARTIFACT_BYTES:
            raise InputError("Invalid or oversized OCR artifact")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != prior["artifacts"].get(name):
            raise InputError("OCR artifact hash mismatch")
        snapshots[name] = data
    if sha256(manifest_path) != manifest_hash:
        raise InputError("OCR manifest changed during replay")
    return prior, snapshots, manifest_hash

