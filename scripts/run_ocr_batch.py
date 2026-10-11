"""Sequential OCR-only batch. No LLM, cloud API, scheduler submission or downloads."""
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sys
import time
import uuid

# Also supports a manually uploaded copy under <repo>/.runtime/ocr-batch/.
ROOT = next(parent for parent in Path(__file__).resolve().parents
            if (parent / "app/ocr_pipeline.py").is_file() and (parent / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT))

from app.core.config import Settings
from app.core.errors import InputError, PipelineError
from app.core.files import contained, json_text, read_json, sha256, write_json
from app.ocr_pipeline import OcrPipeline

EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


def inventory(root: Path, directory: str) -> list[dict]:
    folder = contained(root, directory)
    private = contained(root, "private_inputs")
    if not folder.is_dir() or not folder.is_relative_to(private):
        raise InputError("Batch input must be a directory under private_inputs")
    items = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise InputError("Batch input must not contain symlinks")
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(folder):
            raise InputError("Batch input escapes selected directory")
        items.append({"source": resolved.relative_to(root.resolve()).as_posix(), "sha256": sha256(resolved)})
    if not items:
        raise InputError("No PDF, PNG or JPEG files found")
    return items


@contextmanager
def batch_lock(path: Path):
    """OS lock is released even after job termination; lock file can remain."""
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise InputError("This batch is already running; do not submit it twice") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def verified_run(root: Path, row: dict) -> bool:
    """Do not trust status alone, including after a interrupted summary write."""
    if not row.get("attempts"):
        return False
    run_id = row["attempts"][-1]["run_id"]
    try:
        output = contained(root, f"outputs/{run_id}")
        manifest = read_json(output / "manifest.json")
        if (manifest.get("mode") != "ocr_only" or manifest.get("ocr_status") != "completed"
                or manifest.get("source") != row["source"] or manifest.get("source_sha256") != row["sha256"]):
            return False
        return all(sha256(contained(root, f"outputs/{run_id}/{name}")) == manifest["artifacts"].get(name)
                   for name in ("raw.json", "parsed.md"))
    except (PipelineError, OSError, KeyError, TypeError, AttributeError):
        return False


def save_summary(path: Path, summary: dict) -> None:
    summary["updated_at"] = datetime.now(timezone.utc).isoformat()
    counts = Counter(row["status"] for row in summary["files"])
    summary["counts"] = {name: counts[name] for name in ("pending", "running", "completed", "failed")}
    write_json(path, summary)


def batch(settings: Settings, directory: str, batch_id: str, *, resume: bool = False,
          skip_failed: bool = False, time_budget: float = 0, pipeline=None) -> int:
    if skip_failed and not resume:
        raise InputError("--skip-failed requires --resume")
    root = settings.root.resolve()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,59}", batch_id):
        raise InputError("Invalid batch ID (letters, digits, underscores, hyphens; max 60)")
    started = time.monotonic()
    files = inventory(root, directory)
    destination = contained(root, f"outputs/batches/{batch_id}", must_exist=False)
    destination.mkdir(parents=True, exist_ok=True)
    with batch_lock(destination / ".lock"):
        summary_path = destination / "summary.json"
        identity = {"input_directory": directory, "files": files, "device": settings.device,
                    "model_manifest_sha256": sha256(root / ".models/manifest.json")}
        fingerprint = hashlib.sha256(json_text(identity).encode("utf-8")).hexdigest()
        if summary_path.exists():
            if not resume:
                raise InputError("Batch already exists; use --resume or a new batch ID")
            summary = read_json(summary_path)
            if summary.get("fingerprint") != fingerprint:
                raise InputError("Inputs, device or model manifest changed; use a new batch ID")
            # A killed job may have finished its document before updating summary.
            for row in summary["files"]:
                if verified_run(root, row):
                    row["status"] = "completed"
                    row["attempts"][-1]["status"] = "completed"
                elif (skip_failed and row.get("attempts")
                      and row["attempts"][-1].get("status") == "failed"
                      and row["attempts"][-1].get("error") != "interrupted"):
                    row["status"] = "failed"
                else:
                    row["status"] = "pending"
        else:
            if resume:
                raise InputError("No saved batch exists; omit --resume for the first run")
            summary = {"format": "ocr-batch-v1", "batch_id": batch_id, "fingerprint": fingerprint,
                       "input_directory": directory, "device": settings.device,
                       "model_manifest_sha256": identity["model_manifest_sha256"],
                       "created_at": datetime.now(timezone.utc).isoformat(),
                       "files": [dict(item, status="pending", attempts=[]) for item in files]}
        summary.update(status="running", per_document_timeout=settings.ocr_timeout,
                       skip_failed=skip_failed)
        save_summary(summary_path, summary)
        parser = pipeline if pipeline is not None else OcrPipeline(settings)
        token = hashlib.sha256(batch_id.encode()).hexdigest()[:8]
        for index, row in enumerate(summary["files"], 1):
            if row["status"] == "completed":
                print(f"[{index}/{len(files)}] SKIP completed", flush=True)
                continue
            if skip_failed and row["status"] == "failed":
                print(f"[{index}/{len(files)}] SKIP previously failed", flush=True)
                continue
            # Reserve enough time for the whole per-document timeout + final writes.
            if time_budget and time.monotonic() - started + settings.ocr_timeout + 60 >= time_budget:
                summary["status"] = "paused_time_budget"
                save_summary(summary_path, summary)
                print("Time budget reached; resubmit this batch with --resume.", flush=True)
                return 2
            stem = re.sub(r"[^A-Za-z0-9_-]", "_", Path(row["source"]).stem)[:28] or "document"
            run_id = f"ocrb_{token}_{index:04d}_{stem}_{uuid.uuid4().hex[:8]}"
            attempt = {"run_id": run_id, "output": f"outputs/{run_id}", "status": "running",
                       "timeout_seconds": settings.ocr_timeout,
                       "started_at": datetime.now(timezone.utc).isoformat()}
            row["attempts"].append(attempt)
            row["status"] = "running"
            save_summary(summary_path, summary)
            print(f"[{index}/{len(files)}] START {run_id}", flush=True)
            before = time.monotonic()
            try:
                if sha256(contained(root, row["source"])) != row["sha256"]:
                    raise InputError("Input changed after inventory")
                parser.parse(row["source"], run_id=run_id)
                if not verified_run(root, row):
                    raise PipelineError("OCR output verification failed")
                row["status"] = attempt["status"] = "completed"
            except (Exception, KeyboardInterrupt) as exc:
                # Never record arbitrary provider exceptions or recognized text.
                row["status"] = attempt["status"] = "failed"
                attempt["error"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "ocr_failed"
                if isinstance(exc, KeyboardInterrupt):
                    summary["status"] = "interrupted"
                    raise
            finally:
                attempt["elapsed_seconds"] = round(time.monotonic() - before, 3)
                save_summary(summary_path, summary)
            print(f"[{index}/{len(files)}] {row['status'].upper()} {run_id}", flush=True)
        summary["status"] = "completed_with_failures" if any(r["status"] == "failed" for r in summary["files"]) else "completed"
        save_summary(summary_path, summary)
        print(f"Batch {summary['status']}; summary: outputs/batches/{batch_id}/summary.json", flush=True)
        return 1 if summary["counts"]["failed"] else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Directory under private_inputs; recursive")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--resume", action="store_true", help="Skip verified successes, retry failed/unfinished files once")
    parser.add_argument("--skip-failed", action="store_true",
                        help="With --resume, leave previous failures untouched and process unfinished files")
    parser.add_argument("--time-budget-seconds", type=int, default=0, help="0 disables soft deadline; PBS walltime still applies")
    args = parser.parse_args(argv)
    try:
        if args.time_budget_seconds < 0:
            raise InputError("Time budget must not be negative")
        return batch(Settings.from_ocr_env(), args.input, args.batch_id, resume=args.resume,
                     skip_failed=args.skip_failed, time_budget=args.time_budget_seconds)
    except PipelineError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError:
        print("Batch filesystem error; check input, models and output access.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
