"""Run the local text model in its isolated environment after OCR has exited."""
from dataclasses import asdict
import os
from pathlib import Path
import tempfile

from app.core.config import Settings
from app.core.errors import ExtractionError
from app.core.files import contained, read_json, sha256, write_json
from app.llm.contract import PROMPT_VERSION, assess_response, build_messages
from app.paddleocr.adapter import execute_worker
from app.schemas.invoice import TaxInvoice


class LocalLlmExtractor:
    def __init__(self, settings: Settings):
        self.settings = settings

    def extract(self, markdown: str) -> TaxInvoice:
        temporary = contained(self.settings.root, ".runtime/llm", must_exist=False)
        temporary.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary) as directory:
            return self.extract_to(markdown, Path(directory))

    def extract_to(self, markdown: str, output: Path) -> TaxInvoice:
        root = self.settings.root.resolve()
        if not output.resolve().is_relative_to(root):
            raise ExtractionError("LLM artifacts must remain in the repository")
        if not markdown.strip() or len(markdown) > 200_000:
            raise ExtractionError("LLM requires nonempty OCR text of at most 200000 characters")
        default = ".venv-llm/Scripts/python.exe" if os.name == "nt" else ".venv-llm/bin/python"
        python = contained(root, self.settings.llm_python or default)
        if not python.is_file():
            raise ExtractionError("LLM interpreter missing; create the separate LLM environment")
        request = {
            "prompt_version": PROMPT_VERSION, "messages": build_messages(markdown),
            "device": self.settings.llm_device, "dtype": self.settings.llm_dtype,
            "threads": self.settings.llm_threads, "max_input_tokens": self.settings.llm_max_input_tokens,
            "max_new_tokens": self.settings.llm_max_new_tokens,
        }
        request_path, response_path = output / "llm_request.json", output / "llm_response.json"
        write_json(request_path, request)
        outcome = execute_worker([str(python), "-m", "app.llm.worker",
                                  request_path.relative_to(root).as_posix(),
                                  response_path.relative_to(root).as_posix()], root, self.settings.llm_timeout)
        payload = read_json(response_path) if response_path.exists() else {}
        if not isinstance(payload, dict):
            payload = {"status": "failed", "error_type": "InvalidWorkerPayload"}
        payload["execution"] = asdict(outcome)
        payload["prompt_version"] = PROMPT_VERSION
        payload["request_sha256"] = sha256(request_path)
        if outcome.returncode != 0 or outcome.termination != "exited" or payload.get("status") != "completed":
            payload["status"] = "failed"
            write_json(response_path, payload)
            raise ExtractionError("LLM failed or timed out; inspect local LLM artifacts")
        try:
            assessment = assess_response(payload.get("text"), markdown)
        except ExtractionError:
            payload.update(status="failed", stage="validation", validation="failed",
                           generation_status="completed")
            write_json(response_path, payload)
            raise
        # Evidence concerns accompany format-valid values instead of discarding
        # the whole invoice. Keep the original generated text for auditing.
        write_json(output / "review.json", assessment.review)
        payload["validation"] = "passed_with_review" if assessment.review["requires_review"] else "passed"
        payload["format_validation"] = "passed"
        payload["requires_review"] = assessment.review["requires_review"]
        payload["review_sha256"] = sha256(output / "review.json")
        write_json(response_path, payload)
        return assessment.invoice
