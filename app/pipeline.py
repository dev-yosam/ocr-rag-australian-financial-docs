from pathlib import Path
import re
import shutil
import uuid

from PIL import Image, UnidentifiedImageError

from app.core.config import Settings
from app.core.errors import InputError, PipelineError
from app.core.files import contained, new_run, read_json, sha256, write_json
from app.extraction.invoice import InvoiceExtractor, RuleInvoiceExtractor
from app.schemas.invoice import SCHEMA_VERSION, TaxInvoice
from app.paddleocr.adapter import PaddleParser
from app.paddleocr.normalize import normalize_markdown
from app.paddleocr.types import DocumentParser, PartialParseError
from app.llm.adapter import LocalLlmExtractor

ARTIFACT_NAMES = ("raw.json", "parsed.md", "llm_request.json", "llm_response.json", "review.json", "extracted.json")


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
        self.extractor = extractor or (LocalLlmExtractor(settings) if settings.extractor == "llm" else RuleInvoiceExtractor())

    def _extract(self, markdown: str, output: Path) -> TaxInvoice:
        if isinstance(self.extractor, LocalLlmExtractor):
            return self.extractor.extract_to(markdown, output)
        return self.extractor.extract(markdown)

    def _finish(self, output: Path, manifest: dict) -> None:
        for name in ARTIFACT_NAMES:
            artifact = output / name
            if artifact.is_file():
                manifest["artifacts"][name] = sha256(artifact)
        write_json(output / "manifest.json", manifest)

    def _complete(self, output: Path, invoice: TaxInvoice, manifest: dict) -> None:
        """Persist format-valid values and make review requirements explicit."""
        manifest["status"] = "completed"
        if isinstance(self.extractor, LocalLlmExtractor):
            review = read_json(output / "review.json")
            manifest["review"] = {
                "requires_review": review["requires_review"],
                "issue_count": len(review["issues"]),
                "fields_requiring_review": sorted(
                    {field for field, detail in review["fields"].items() if detail["status"] == "needs_review"}
                    | {issue["field"] for issue in review["issues"]}
                ),
                "missing_fields": review["missing_fields"],
                "semantic_accuracy_verified": False,
            }
            if review["requires_review"]:
                manifest["status"] = "completed_needs_review"
        write_json(output / "extracted.json", invoice.model_dump(mode="python"))

    @staticmethod
    def _result(run_id: str, invoice: TaxInvoice, manifest: dict) -> dict:
        return {
            "run_id": run_id, "invoice": invoice.model_dump(mode="python"),
            "status": manifest["status"],
            "requires_review": manifest.get("review", {}).get("requires_review", False),
            "review": manifest.get("review"),
            "artifacts": {name: f"outputs/{run_id}/{name}" for name in manifest["artifacts"]},
        }

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
            "extraction": {"strategy": self.settings.extractor},
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
            invoice = self._extract(markdown, output)
            self._complete(output, invoice, manifest)
        except Exception:
            # This is the outer document-processing trust boundary. Provider and
            # validation exceptions may contain source text; all failures must
            # close the audit record and expose only a sanitized error.
            manifest["status"] = "failed"
            # Validation error strings can embed input values, so never expose them.
            raise PipelineError("Invoice processing failed; inspect local artifacts and prerequisites") from None
        finally:
            self._finish(output, manifest)
        return self._result(run_id, invoice, manifest)

    def reextract(self, directory: str, run_id: str | None = None) -> dict:
        """Replay hash-verified OCR artifacts into a NEW run without loading OCR."""
        root = self.settings.root.resolve()
        previous = contained(root, directory)
        if not previous.is_dir() or not previous.is_relative_to(contained(root, "outputs")):
            raise InputError("Choose a previous output run")
        previous_manifest = contained(root, f"{directory}/manifest.json")
        prior = read_json(previous_manifest)
        if not isinstance(prior, dict) or not isinstance(prior.get("artifacts"), dict):
            raise InputError("Invalid previous run manifest")
        for name in ("raw.json", "parsed.md"):
            path = contained(root, f"{directory}/{name}")
            if not path.is_file() or sha256(path) != prior["artifacts"].get(name):
                raise InputError("Previous OCR artifacts do not match their manifest")
        source = prior.get("source")
        source_hash = prior.get("source_sha256")
        if (not isinstance(source, str) or not isinstance(source_hash, str)
                or re.fullmatch(r"[0-9a-f]{64}", source_hash) is None
                or not isinstance(prior.get("versions"), dict)):
            raise InputError("Missing previous source provenance")
        contained(root, source, must_exist=False)
        run_id = run_id or uuid.uuid4().hex
        output = new_run(root, run_id)
        manifest = {
            "schema_version": SCHEMA_VERSION, "run_id": run_id, "status": "processing",
            "source": source, "source_sha256": prior.get("source_sha256"),
            "versions": prior.get("versions", {}), "artifacts": {},
            "extraction": {"strategy": self.settings.extractor},
            "replayed_from": {"directory": previous.relative_to(root).as_posix(),
                              "manifest_sha256": sha256(previous_manifest)},
        }
        write_json(output / "manifest.json", manifest)
        try:
            for name in ("raw.json", "parsed.md"):
                shutil.copyfile(contained(root, f"{directory}/{name}"), output / name)
                if sha256(output / name) != prior["artifacts"][name]:
                    raise InputError("Previous OCR artifacts changed during replay")
            markdown = (output / "parsed.md").read_text(encoding="utf-8")
            invoice = self._extract(markdown, output)
            self._complete(output, invoice, manifest)
        except Exception:
            manifest["status"] = "failed"
            raise PipelineError("Invoice extraction failed; inspect local artifacts and prerequisites") from None
        finally:
            self._finish(output, manifest)
        return self._result(run_id, invoice, manifest)
