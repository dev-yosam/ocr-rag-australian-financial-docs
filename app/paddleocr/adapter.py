from dataclasses import dataclass
import time
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from app.core.config import Settings
from app.core.errors import ParserError
from app.core.files import contained, read_json
from app.paddleocr.types import ParsedDocument, PartialParseError


@dataclass(frozen=True)
class WorkerOutcome:
    returncode: int
    termination: str
    elapsed_seconds: float


def execute_worker(command: list[str], root: Path, timeout: float) -> WorkerOutcome:
    """Own the process tree, including Windows venv redirector children."""
    started = time.monotonic()
    with subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
        try:
            code = process.wait(timeout=timeout)
            return WorkerOutcome(code, "exited", round(time.monotonic() - started, 3))
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, check=False)
            process.kill()
            process.wait()
            reason = "timeout" if isinstance(error, subprocess.TimeoutExpired) else "interrupted"
            return WorkerOutcome(process.returncode, reason, round(time.monotonic() - started, 3))


class PaddleParser:
    def __init__(self, settings: Settings, *, timeout: float | None = None):
        self.settings = settings
        self.timeout = settings.ocr_timeout if timeout is None else timeout

    def parse(self, path: Path) -> ParsedDocument:
        root = self.settings.root.resolve()
        manifest = contained(root, ".models/manifest.json", must_exist=False)
        if not manifest.is_file():
            raise ParserError("Models missing; run scripts/prepare_models.py explicitly")
        temporary = contained(root, ".runtime/ocr", must_exist=False)
        temporary.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary) as directory:
            result = Path(directory) / "result.json"
            # Interpreter is project-local. No shell, downloaded executables, or logs.
            outcome = execute_worker(
                [sys.executable, "-m", "app.paddleocr.worker", str(path), str(result),
                 self.settings.device], root, self.timeout)
            payload = read_json(result) if result.exists() else {}
            pages = payload.get("raw_pages", [])
            if outcome.returncode != 0 or outcome.termination != "exited" or payload.get("status") != "completed":
                raise PartialParseError("PaddleOCR failed or timed out; see environment checks", pages,
                                        {"stage": payload.get("stage", "worker_start"),
                                         "error_type": payload.get("error_type", {"timeout": "WorkerTimeout", "interrupted": "WorkerInterrupted"}.get(outcome.termination, "WorkerExit")),
                                         "returncode": outcome.returncode,
                                         "termination": outcome.termination,
                                         "elapsed_seconds": outcome.elapsed_seconds,
                                         "timeout_seconds": self.timeout,
                                         "versions": payload.get("versions", {})})
            return ParsedDocument(pages, payload["markdown_pages"], payload["versions"])
