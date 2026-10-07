"""Document parsing only: no invoice extractor or LLM runtime is constructed."""
import time
import uuid

from app.core.config import Settings
from app.core.documents import check_document
from app.core.errors import ParserError, PipelineError
from app.core.files import contained, new_run, sha256, write_json
from app.paddleocr.adapter import PaddleParser
from app.paddleocr.normalize import normalize_markdown
from app.paddleocr.types import DocumentParser, PartialParseError


OCR_ARTIFACT_NAMES = ("raw.json", "parsed.md")


class OcrPipeline:
    def __init__(self, settings: Settings, parser: DocumentParser | None = None):
        self.settings = settings
        self.parser = parser if parser is not None else PaddleParser(settings)

    def parse(self, source: str, run_id: str | None = None) -> dict:
        root = self.settings.root.resolve()
        path = contained(root, source)
        check_document(path)
        run_id = run_id or uuid.uuid4().hex
        output = new_run(root, run_id)
        manifest = {
            "schema_version": "ocr-run-v1", "mode": "ocr_only", "run_id": run_id,
            "status": "processing", "ocr_status": "processing", "stage": "parsing",
            "source": path.relative_to(root).as_posix(), "source_sha256": sha256(path),
            "versions": {}, "artifacts": {},
            "settings": {"device": self.settings.device, "ocr_timeout_seconds": self.settings.ocr_timeout},
            "extraction": {"strategy": "none", "status": "not_requested"},
            "semantic_accuracy_verified": False,
        }
        write_json(output / "manifest.json", manifest)
        started = time.monotonic()
        try:
            try:
                document = self.parser.parse(path)
            except PartialParseError as error:
                if error.raw_pages:
                    write_json(output / "raw.json", error.raw_pages)
                manifest["failure"] = error.diagnostic
                manifest["versions"] = error.diagnostic.get("versions", {})
                raise
            # Save provider results unchanged, even if Markdown conversion fails.
            write_json(output / "raw.json", document.raw_pages)
            manifest["versions"] = document.versions
            manifest["stage"] = "normalizing_markdown"
            write_json(output / "manifest.json", manifest)
            if not document.raw_pages or len(document.raw_pages) != len(document.markdown_pages):
                raise ParserError("Incomplete OCR page results")
            markdown = normalize_markdown(document.markdown_pages)
            (output / "parsed.md").write_text(markdown, encoding="utf-8", newline="\n")
            manifest.update(status="completed", ocr_status="completed", stage="completed",
                            page_count=len(document.raw_pages))
        except (Exception, KeyboardInterrupt) as error:
            manifest.update(status="failed", ocr_status="failed")
            if "failure" not in manifest:
                manifest["failure"] = {"stage": manifest["stage"], "error_type": type(error).__name__}
            # Never expose provider exceptions or document content.
            raise PipelineError("OCR parsing failed; inspect local artifacts and prerequisites") from None
        finally:
            manifest["elapsed_seconds"] = round(time.monotonic() - started, 3)
            for name in OCR_ARTIFACT_NAMES:
                file = output / name
                if file.is_file():
                    manifest["artifacts"][name] = sha256(file)
            write_json(output / "manifest.json", manifest)
        return {
            "run_id": run_id, "mode": "ocr_only", "status": manifest["status"],
            "ocr_status": manifest["ocr_status"], "page_count": manifest["page_count"],
            "artifacts": {name: f"outputs/{run_id}/{name}"
                          for name in (*OCR_ARTIFACT_NAMES, "manifest.json")},
        }
