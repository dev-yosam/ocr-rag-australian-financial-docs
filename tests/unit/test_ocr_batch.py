"""Batch tests use synthetic PDFs and a fake parser; no PBS, OCR or network."""
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import InputError, PipelineError
from app.core.files import read_json, write_json
from app.ocr_pipeline import OcrPipeline
from app.paddleocr.types import ParsedDocument
from scripts.run_ocr_batch import batch, batch_lock, inventory


@pytest.fixture
def batch_repo(tmp_path):
    for name in ("a/same.pdf", "b/same.pdf", "b/sp ace.PDF"):
        path = tmp_path / "private_inputs/synthetic" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF- synthetic fixture")
    (tmp_path / ".models").mkdir()
    write_json(tmp_path / ".models/manifest.json", {"synthetic": True})
    return tmp_path


class FakeParser:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def parse(self, path):
        self.calls.append(path)
        if self.fail and path.parent.name == "a":
            raise PipelineError("SYNTHETIC CONTENT MUST NOT LEAK")
        return ParsedDocument([{"fixture": "synthetic"}], ["SYNTHETIC TEXT"], {"fixture": "fake"})


def run(root, parser, **kwargs):
    settings = Settings(root=root, ocr_timeout=30)
    return batch(settings, "private_inputs/synthetic", "synthetic-batch",
                 pipeline=OcrPipeline(settings, parser=parser), **kwargs)


def summary(root):
    return read_json(root / "outputs/batches/synthetic-batch/summary.json")


def test_sequential_nested_files_unique_outputs_and_no_extraction(batch_repo):
    parser = FakeParser()
    assert run(batch_repo, parser) == 0
    result = summary(batch_repo)
    assert result["counts"]["completed"] == 3 and len(parser.calls) == 3
    run_ids = {r["attempts"][-1]["run_id"] for r in result["files"]}
    assert len(run_ids) == 3
    for run_id in run_ids:
        output = batch_repo / "outputs" / run_id
        assert {p.name for p in output.iterdir()} == {"raw.json", "parsed.md", "manifest.json"}
        assert read_json(output / "manifest.json")["mode"] == "ocr_only"


def test_failure_continues_and_resume_only_retries_failure(batch_repo, capsys):
    assert run(batch_repo, FakeParser(fail=True)) == 1
    first = summary(batch_repo)
    assert first["counts"]["failed"] == 1 and first["counts"]["completed"] == 2
    parser = FakeParser()
    assert run(batch_repo, parser, resume=True) == 0
    assert len(parser.calls) == 1
    assert len(summary(batch_repo)["files"][0]["attempts"]) == 2
    assert "SYNTHETIC CONTENT MUST NOT LEAK" not in capsys.readouterr().out


def test_resume_verifies_artifact_hashes(batch_repo):
    run(batch_repo, FakeParser())
    row = summary(batch_repo)["files"][1]
    (batch_repo / row["attempts"][-1]["output"] / "raw.json").write_text("tampered")
    parser = FakeParser()
    assert run(batch_repo, parser, resume=True) == 0
    assert len(parser.calls) == 1


def test_skip_failed_resumes_pending_and_preserves_previous_attempts(batch_repo):
    run(batch_repo, FakeParser(fail=True))
    previous = summary(batch_repo)
    failed_attempts = previous["files"][0]["attempts"]
    completed_attempts = previous["files"][1]["attempts"]
    # Model a paused batch with one failed, one completed and one unstarted file.
    previous["files"][2].update(status="pending", attempts=[])
    previous["status"] = "paused_time_budget"
    write_json(batch_repo / "outputs/batches/synthetic-batch/summary.json", previous)
    parser = FakeParser()
    settings = Settings(root=batch_repo, ocr_timeout=300)
    assert batch(settings, "private_inputs/synthetic", "synthetic-batch",
                 resume=True, skip_failed=True,
                 pipeline=OcrPipeline(settings, parser=parser)) == 1
    result = summary(batch_repo)
    assert [p.name for p in parser.calls] == ["sp ace.PDF"]
    assert result["counts"] == {"pending": 0, "running": 0, "completed": 2, "failed": 1}
    assert result["status"] == "completed_with_failures"
    assert result["files"][0]["attempts"] == failed_attempts
    assert result["files"][1]["attempts"] == completed_attempts
    assert result["per_document_timeout"] == 300
    assert result["files"][2]["attempts"][-1]["timeout_seconds"] == 300
    assert run(batch_repo, FakeParser(), resume=True, skip_failed=True) == 1
    # Normal resume can still explicitly retry the deferred failure later.
    retry = FakeParser()
    assert run(batch_repo, retry, resume=True) == 0
    assert len(retry.calls) == 1


def test_skip_failed_requires_resume(batch_repo):
    with pytest.raises(InputError, match="requires --resume"):
        run(batch_repo, FakeParser(), skip_failed=True)


def test_skip_failed_recovers_interrupted_and_rechecks_success(batch_repo):
    run(batch_repo, FakeParser(fail=True))
    state = summary(batch_repo)
    state["files"][0]["attempts"][-1]["error"] = "interrupted"
    write_json(batch_repo / "outputs/batches/synthetic-batch/summary.json", state)
    row = state["files"][1]
    (batch_repo / row["attempts"][-1]["output"] / "raw.json").write_text("tampered")
    parser = FakeParser()
    assert run(batch_repo, parser, resume=True, skip_failed=True) == 0
    assert len(parser.calls) == 2


def test_recover_completion_after_summary_interrupted(batch_repo):
    run(batch_repo, FakeParser())
    result = summary(batch_repo)
    result["files"][0]["status"] = "running"
    result["files"][0]["attempts"][-1]["status"] = "running"
    write_json(batch_repo / "outputs/batches/synthetic-batch/summary.json", result)
    parser = FakeParser()
    assert run(batch_repo, parser, resume=True) == 0
    assert not parser.calls
    assert summary(batch_repo)["files"][0]["attempts"][-1]["status"] == "completed"


@pytest.mark.parametrize("change", ["input", "new_file", "model"])
def test_changed_batch_rejected(batch_repo, change):
    run(batch_repo, FakeParser())
    if change == "input":
        (batch_repo / "private_inputs/synthetic/a/same.pdf").write_bytes(b"%PDF- changed")
    elif change == "new_file":
        (batch_repo / "private_inputs/synthetic/new.pdf").write_bytes(b"%PDF- new")
    else:
        write_json(batch_repo / ".models/manifest.json", {"synthetic": "changed"})
    with pytest.raises(InputError, match="changed"):
        run(batch_repo, FakeParser(), resume=True)


def test_soft_budget_and_resume(batch_repo):
    parser = FakeParser()
    assert run(batch_repo, parser, time_budget=20) == 2
    assert not parser.calls and summary(batch_repo)["status"] == "paused_time_budget"
    assert run(batch_repo, parser, resume=True) == 0


def test_new_vs_resume_is_explicit(batch_repo):
    with pytest.raises(InputError, match="No saved batch"):
        run(batch_repo, FakeParser(), resume=True)
    run(batch_repo, FakeParser())
    with pytest.raises(InputError, match="already exists"):
        run(batch_repo, FakeParser())


def test_invalid_input_and_batch_id(batch_repo):
    with pytest.raises(InputError):
        inventory(batch_repo, ".models")
    with pytest.raises(InputError):
        batch(Settings(root=batch_repo), "private_inputs/synthetic", "../escape")


def test_os_lock_prevents_concurrent_batch(tmp_path):
    with batch_lock(tmp_path / ".lock"):
        with pytest.raises(InputError, match="already running"):
            with batch_lock(tmp_path / ".lock"):
                pytest.fail("Lock not enforced")
    with batch_lock(tmp_path / ".lock"):
        pass


def test_unsupported_files_ignored(batch_repo):
    (batch_repo / "private_inputs/synthetic/notes.txt").write_text("synthetic")
    assert len(inventory(batch_repo, "private_inputs/synthetic")) == 3
