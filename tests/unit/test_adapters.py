import subprocess
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import ParserError, RagFlowError
from app.core.files import read_json, write_json
from app.paddleocr.adapter import PaddleParser, WorkerOutcome, execute_worker
from app.paddleocr.types import PartialParseError
from app.paddleocr.worker import collect, deny_network
from app.rag.client import RagFlowClient, safe_base_url
from app.rag.artifacts import submit
from app.pipeline import InvoicePipeline


def test_missing_models_fail_before_starting_worker(repo, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Worker must not start without prepared models")
    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(ParserError, match="Models missing"):
        PaddleParser(Settings(root=repo)).parse(repo / "invoice.png")


def test_worker_contract_and_output_suppression(repo, monkeypatch):
    (repo / ".models").mkdir()
    write_json(repo / ".models/manifest.json", {})
    def run(args, root, timeout):
        assert args[1:3] == ["-m", "app.paddleocr.worker"]
        assert args[-1] == "cpu"
        write_json(__import__("pathlib").Path(args[4]), {"status": "completed", "raw_pages": [{"raw": 1}],
            "markdown_pages": ["text"], "versions": {"pipeline": "PaddleOCR-VL-1.6"}})
        return WorkerOutcome(0, "exited", 0.1)
    monkeypatch.setattr("app.paddleocr.adapter.execute_worker", run)
    result = PaddleParser(Settings(root=repo)).parse(repo / "invoice.png")
    assert result.raw_pages == [{"raw": 1}]
    assert result.versions["pipeline"] == "PaddleOCR-VL-1.6"


def test_raw_survives_markdown_failure(repo):
    class BrokenPage:
        json = {"res": {"text": "FAKE RAW"}}
        @property
        def markdown(self):
            raise ValueError("conversion failed")
    class Fake:
        def predict_iter(self, path):
            yield BrokenPage()
    target = repo / "result.json"
    with pytest.raises(ValueError):
        collect(Fake(), repo / "invoice.png", target, {"pipeline": "FAKE"})
    assert read_json(target)["raw_pages"] == [BrokenPage.json]
    assert read_json(target)["status"] == "processing"


def test_ocr_network_hook():
    with pytest.raises(RuntimeError):
        deny_network("socket.connect", ())
    deny_network("open", ())


def test_explicit_vl16_complete_pipeline_configuration(repo, monkeypatch):
    import sys
    from app.paddleocr import worker
    calls = {}
    class FakePipeline:
        def __init__(self, **kwargs):
            calls.update(kwargs)
        def predict_iter(self, source):
            yield SimpleNamespace(json={"res": {}}, markdown={"markdown_texts": "FAKE"})
    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(PaddleOCRVL=FakePipeline))
    monkeypatch.setattr(worker, "ROOT", repo)
    monkeypatch.setattr(worker, "local_runtime", lambda root: None)
    monkeypatch.setattr(worker, "model_directories", lambda root: {"layout": "local-layout", "recognition": "local-vl"})
    monkeypatch.setattr(worker.importlib.metadata, "version", lambda name: worker.EXPECTED[name])
    monkeypatch.setattr(sys, "addaudithook", lambda hook: None)
    monkeypatch.setattr(sys, "argv", ["worker", str(repo / "invoice.png"), str(repo / "result.json"), "cpu"])
    assert worker.main() == 0
    assert calls["pipeline_version"] == "v1.6"
    assert calls["use_layout_detection"] is True
    assert calls["device"] == "cpu"
    assert calls["vl_rec_model_dir"] == "local-vl"


@pytest.mark.parametrize("url", ["https://cloud.ragflow.io", "https://8.8.8.8", "http://user:key@localhost", "http://localhost/path"])
def test_external_rag_destinations_rejected(url):
    with pytest.raises(RagFlowError):
        safe_base_url(url)


def test_ragflow_http_contract():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer FAKE_TEST_KEY"
        if request.method == "POST" and request.url.path.endswith("/documents"):
            assert "multipart/form-data" in request.headers["content-type"]
            assert b'name="file"' in request.content
            return httpx.Response(200, json={"code": 0, "data": [{"id": "doc1"}]})
        if request.method == "POST":
            assert request.read() == b'{"document_ids":["doc1"]}'
            return httpx.Response(200, json={"code": 0})
        return httpx.Response(200, json={"code": 0, "data": {"docs": [{"id": "doc1", "run": "3"}]}})
    client = RagFlowClient("http://localhost:9380", "FAKE_TEST_KEY", transport=httpx.MockTransport(handler))
    try:
        assert client.upload_markdown("ds", "synthetic.md", b"FAKE") == "doc1"
        client.start_parsing("ds", "doc1")
        assert client.get_status("ds", "doc1") == "completed"
        assert len(calls) == 3
    finally:
        client.close()


@pytest.mark.parametrize("status,payload", [(401, {"error": "SECRET"}), (200, {"code": 109, "message": "SECRET"}),
    (200, {"code": 0, "data": {}}), (302, {}), (200, ["SECRET"]),
    (200, {"code": 0, "data": [{"id": None}]})])
def test_rag_errors_sanitized(status, payload):
    client = RagFlowClient("http://localhost:9380", "FAKE_TEST_KEY",
        transport=httpx.MockTransport(lambda r: httpx.Response(status, json=payload)))
    try:
        with pytest.raises(RagFlowError) as error:
            client.upload_markdown("ds", "fake.md", b"SYNTHETIC")
        assert "SECRET" not in str(error.value)
    finally:
        client.close()


def test_timeout_and_duplicate_prevention(repo, fake_parser):
    InvoicePipeline(Settings(root=repo), fake_parser).process("invoice.png", "sample")
    def timeout(request):
        raise httpx.ReadTimeout("SECRET", request=request)
    client = RagFlowClient("http://localhost", "FAKE_TEST_KEY", transport=httpx.MockTransport(timeout))
    settings = Settings(root=repo, ragflow_dataset_id="ds")
    try:
        with pytest.raises(RagFlowError):
            submit(settings, "outputs/sample", client)
        assert read_json(repo / "outputs/sample/ragflow.json")["status"] == "submission_pending"
        with pytest.raises(RagFlowError, match="already attempted"):
            submit(settings, "outputs/sample", client)
    finally:
        client.close()


@pytest.mark.parametrize("mode", ["exited", "timeout", "interrupted"])
def test_worker_termination_diagnostics(repo, monkeypatch, mode):
    class Process:
        pid = 12345
        returncode = 7
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def wait(self, timeout=None):
            if timeout is not None:
                if mode == "timeout": raise subprocess.TimeoutExpired("FAKE", timeout)
                if mode == "interrupted": raise KeyboardInterrupt()
            return self.returncode
        def kill(self): self.returncode = -9
    def popen(*args, **kwargs):
        assert kwargs["stdout"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.DEVNULL
        return Process()
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)
    result = execute_worker(["FAKE"], repo, 1)
    assert result.termination == mode
    assert result.returncode == (7 if mode == "exited" else -9)
    assert result.elapsed_seconds >= 0


@pytest.mark.parametrize("termination,code,error_type", [
    ("timeout", -9, "WorkerTimeout"), ("exited", 7, "WorkerExit"),
    ("interrupted", -9, "WorkerInterrupted")])
def test_parser_preserves_termination_and_partial_raw(repo, monkeypatch, termination, code, error_type):
    (repo / ".models").mkdir()
    write_json(repo / ".models/manifest.json", {})
    def run(args, root, timeout):
        from pathlib import Path
        write_json(Path(args[4]), {"stage": "parsing", "raw_pages": [{"text": "FAKE"}]})
        return WorkerOutcome(code, termination, 2.5)
    monkeypatch.setattr("app.paddleocr.adapter.execute_worker", run)
    with pytest.raises(PartialParseError) as caught:
        PaddleParser(Settings(root=repo)).parse(repo / "invoice.png")
    assert caught.value.diagnostic["error_type"] == error_type
    assert caught.value.diagnostic["returncode"] == code
    assert caught.value.diagnostic["elapsed_seconds"] == 2.5
    assert caught.value.raw_pages == [{"text": "FAKE"}]
