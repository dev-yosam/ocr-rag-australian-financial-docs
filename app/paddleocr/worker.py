"""Private subprocess entrypoint: all stdout/stderr discarded by the adapter."""
import importlib.metadata
import json
from pathlib import Path
import sys

from app.core.config import ROOT, local_runtime
from app.core.files import contained, read_json, sha256, write_json

EXPECTED = {"paddleocr": "3.6.0", "paddlex": "3.6.0", "paddlepaddle": "3.2.1"}


def deny_network(event: str, args: tuple) -> None:
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("Network disabled during OCR")


def model_directories(root: Path) -> dict[str, str]:
    manifest = read_json(contained(root, ".models/manifest.json"))
    if manifest.get("pipeline_version") != "v1.6":
        raise ValueError("Incorrect model version")
    directories = {}
    for role in ("layout", "recognition"):
        model = manifest["models"][role]
        path = contained(root, model["path"])
        if not model["files"]:
            raise ValueError("Empty model")
        for name, digest in model["files"].items():
            file = contained(root, (path / name).relative_to(root).as_posix())
            if sha256(file) != digest:
                raise ValueError("Model checksum mismatch")
        directories[role] = str(path)
    return directories


def collect(pipeline, source: Path, result_path: Path, versions: dict) -> None:
    payload = {"raw_pages": [], "markdown_pages": [], "versions": versions,
               "status": "processing", "stage": "parsing"}
    write_json(result_path, payload)
    for page in pipeline.predict_iter(str(source)):
        raw = page.json
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise ValueError("Unexpected raw result shape")
        payload["raw_pages"].append(raw)
        # Persist provider JSON before attempting Markdown conversion.
        write_json(result_path, payload)
        markdown = page.markdown
        text = markdown["markdown_texts"]
        if not isinstance(text, str):
            raise ValueError("Unexpected Markdown result shape")
        payload["markdown_pages"].append(text)
        write_json(result_path, payload)
    if not payload["raw_pages"]:
        raise ValueError("No pages")
    payload["status"] = "completed"
    write_json(result_path, payload)


def main() -> int:
    source, target, device = sys.argv[1:]
    target = Path(target)
    progress = {"status": "initializing", "stage": "runtime_setup", "raw_pages": []}
    write_json(target, progress)
    local_runtime(ROOT)
    sys.addaudithook(deny_network)
    versions = {name: importlib.metadata.version(name) for name in EXPECTED}
    if versions != EXPECTED:
        raise ValueError("OCR dependency version mismatch")
    progress.update(stage="model_checksums", versions=versions)
    write_json(target, progress)
    directories = model_directories(ROOT)
    progress["stage"] = "importing_paddleocr"
    write_json(target, progress)
    from paddleocr import PaddleOCRVL
    progress["stage"] = "pipeline_initialization"
    write_json(target, progress)
    pipeline = PaddleOCRVL(
        pipeline_version="v1.6", device=device, use_queues=False,
        use_doc_orientation_classify=False, use_doc_unwarping=False,
        use_layout_detection=True,
        layout_detection_model_dir=directories["layout"],
        vl_rec_model_dir=directories["recognition"],
    )
    versions["pipeline"] = "PaddleOCR-VL-1.6"
    collect(pipeline, Path(source), target, versions)
    return 0


if __name__ == "__main__":
    # Provider exceptions may contain document text. This worker's output is never
    # exposed; the parent returns only a content-free error and partial artifacts.
    try:
        result = main()
    except Exception as error:
        # The worker is a third-party trust boundary: retain only the exception
        # class/stage, never its potentially sensitive message or traceback.
        target = Path(sys.argv[2])
        payload = read_json(target) if target.exists() else {"raw_pages": []}
        payload.update(status="failed", error_type=type(error).__name__)
        write_json(target, payload)
        result = 1
    raise SystemExit(result)
