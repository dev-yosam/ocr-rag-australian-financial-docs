from pathlib import Path
import uuid

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import InputError, PipelineError
from app.core.files import contained, new_run, sha256, write_json
from app.extraction.invoice import InvoiceExtractor, RuleInvoiceExtractor
from app.schemas.invoice import SCHEMA_VERSION
from app.paddleocr.adapter import PaddleParser
from app.paddleocr.normalize import normalize_markdown
from app.paddleocr.types import DocumentParser, PartialParseError


def check_document(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0 or path.stat().st_size > 20 * 1024 * 1024:
        raise InputError("Document must be a nonempty file of at most 20 MiB")
    if path.suffix.lower() == ".pdf":
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise InputError("Invalid PDF signature")
    elif path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        try:
            with Image.open(path) as image:
                if image.width * image.height > 25_000_000:
                    raise InputError("Image exceeds 25 megapixels")
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise InputError("Invalid image") from None
    else:
        raise InputError("Supported formats: PDF, PNG, JPEG")


class InvoicePipeline:
    def __init__(self, settings: Settings, parser: DocumentParser | None = None,
                 extractor: InvoiceExtractor | None = None):
        self.settings = settings
        self.parser = parser or PaddleParser(settings)
        self.extractor = extractor or RuleInvoiceExtractor()

    def process(self, source: str, run_id: str | None = None) -> dict:
        root = self.settings.root.resolve()
        path = contained(root, source)
        check_document(path)
        run_id = run_id or uuid.uuid4().hex
        output = new_run(root, run_id)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id, "status": "processing", "source": path.relative_to(root).as_posix(),
            "source_sha256": sha256(path), "versions": {}, "artifacts": {},
        }
        write_json(output / "manifest.json", manifest)
        try:
            try:
                document = self.parser.parse(path)
            except PartialParseError as error:
                if error.raw_pages:
                    write_json(output / "raw.json", error.raw_pages)
                manifest["failure"] = error.diagnostic
                raise
            write_json(output / "raw.json", document.raw_pages)
            manifest["versions"] = document.versions
            markdown = normalize_markdown(document.markdown_pages)
            (output / "parsed.md").write_text(markdown, encoding="utf-8", newline="\n")
            invoice = self.extractor.extract(markdown)
            write_json(output / "extracted.json", invoice.model_dump(mode="python"))
            manifest["status"] = "completed"
        except Exception:
            # This is the outer document-processing trust boundary. Provider and
            # validation exceptions may contain source text; all failures must
            # close the audit record and expose only a sanitized error.
            manifest["status"] = "failed"
            # Validation error strings can embed input values, so never expose them.
            raise PipelineError("Invoice processing failed; inspect local artifacts and prerequisites") from None
        finally:
            for name in ("raw.json", "parsed.md", "extracted.json"):
                artifact = output / name
                if artifact.is_file():
                    manifest["artifacts"][name] = sha256(artifact)
            write_json(output / "manifest.json", manifest)
        return {
            "run_id": run_id, "invoice": invoice.model_dump(mode="python"),
            "artifacts": {name: f"outputs/{run_id}/{name}" for name in manifest["artifacts"]},
        }
