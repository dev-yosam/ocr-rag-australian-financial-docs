"""Replay verified OCR artifacts through Gemini without an OCR/Qwen environment."""
from datetime import datetime, timezone
from pathlib import Path
import time
import uuid

from app.core.errors import InputError, PipelineError
from app.core.files import new_run, sha256, write_json
from app.gemini.client import GeminiClient, GeminiError
from app.gemini.config import GeminiSettings
from app.gemini.contract import PROMPT_VERSION, assess, build_request, ocr_blocks, strict_json
from app.extraction.ocr_artifacts import load_ocr
from app.schemas.tirbic_llm import SCHEMA_VERSION

ARTIFACTS = ("raw.json", "parsed.md", "ocr_blocks.json", "llm_request.json",
             "llm_response.json", "validation.json", "review.json", "extracted.json")


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
