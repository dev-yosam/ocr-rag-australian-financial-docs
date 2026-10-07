"""Replay verified OCR artifacts through Gemini without an OCR/Qwen environment."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import time
import uuid

from app.core.errors import InputError, PipelineError
from app.core.files import contained, new_run, read_json, sha256, write_json
from app.gemini.client import GeminiClient, GeminiError
from app.gemini.config import GeminiSettings
from app.gemini.contract import PROMPT_VERSION, assess, build_request, ocr_blocks, strict_json
from app.schemas.invoice import SCHEMA_VERSION

MAX_ARTIFACT_BYTES = 32_000_000
ARTIFACTS = ("raw.json", "parsed.md", "ocr_blocks.json", "llm_request.json",
             "llm_response.json", "validation.json", "review.json", "extracted.json")


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


class GeminiPipeline:
    def __init__(self, root: Path, settings: GeminiSettings, client=None):
        self.root, self.settings = root, settings
        self.client = client

    def reextract(self, directory: str, run_id: str | None = None, *, dry_run: bool = False) -> dict:
        prior, snapshots, manifest_hash = load_ocr(self.root, directory)
        try:
            document = ocr_blocks(strict_json(snapshots["raw.json"].decode("utf-8")))
        except (ValueError, UnicodeError, RecursionError):
            raise InputError("Invalid OCR JSON") from None
        if not dry_run and not self.settings.api_key:
            raise InputError("GEMINI_API_KEY is required")
        request = build_request(document, self.settings.max_output_tokens)
        run_id = run_id or "gemini_" + uuid.uuid4().hex
        output = new_run(self.root, run_id)
        started = time.monotonic()
        manifest = {
            "run_id": run_id, "schema_version": SCHEMA_VERSION, "mode": "cloud_extraction",
            "status": "running", "stage": "preparation", "ocr_status": "reused",
            "source": prior["source"], "source_sha256": prior["source_sha256"],
            "versions": prior["versions"], "model": self.settings.model, "prompt_version": PROMPT_VERSION,
            "provider": "google_gemini_api", "network_attempted": False,
            "semantic_accuracy_verified": False,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "replayed_from": {"directory": directory, "manifest_sha256": manifest_hash},
            "settings": {"timeout_seconds": self.settings.timeout,
                         "max_output_tokens": self.settings.max_output_tokens},
            "page_count": len(document["pages"]),
        }
        try:
            for name, data in snapshots.items():
                (output / name).write_bytes(data)
            write_json(output / "ocr_blocks.json", document)
            write_json(output / "llm_request.json", request)
            if dry_run:
                manifest.update(status="prepared", stage="prepared")
            else:
                manifest.update(stage="request", network_attempted=True)
                write_json(output / "manifest.json", manifest)
                client = self.client or GeminiClient(self.settings)
                text, metadata = client.generate(request, output)
                manifest["generation"] = metadata
                manifest["stage"] = "validation"
                invoice, validation, review = assess(text, document)
                write_json(output / "validation.json", validation)
                write_json(output / "review.json", review)
                if invoice is None:
                    raise GeminiError("invalid_invoice_contract")
                write_json(output / "extracted.json", invoice)
                manifest.update(status="completed_needs_review" if review["issues"] else "completed", stage="completed")
        except Exception as exc:
            manifest.update(status="failed", error=exc.code if isinstance(exc, GeminiError) else "local_failure")
            if not (output / "validation.json").exists():
                write_json(output / "validation.json", {"valid": False, "not_performed": True,
                                                        "errors": [{"code": manifest["error"]}]})
            # No stale success artifact, even on a late local write failure.
            (output / "extracted.json").unlink(missing_ok=True)
            raise PipelineError(f"Gemini extraction failed: {manifest['error']}; run_id={run_id}") from None
        finally:
            manifest["elapsed_seconds"] = round(time.monotonic() - started, 3)
            manifest["artifacts"] = {name: sha256(output / name) for name in ARTIFACTS if (output / name).is_file()}
            write_json(output / "manifest.json", manifest)
        return {"run_id": run_id, "status": manifest["status"],
                "artifacts": {name: f"outputs/{run_id}/{name}" for name in manifest["artifacts"]}}
