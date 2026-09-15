from pathlib import Path
import socket
import uuid

import pytest
from PIL import Image

from app.paddleocr.types import ParsedDocument

ROOT = Path(__file__).resolve().parents[1]


def pytest_configure(config):
    # Keep test artifacts in this repository, with no reuse/deletion of previous
    # runs (important across Windows sandbox sessions with different ACLs).
    if config.option.basetemp is None:
        config.option.basetemp = str(ROOT / ".runtime" / ("pytest-" + uuid.uuid4().hex))


@pytest.fixture(autouse=True)
def unit_network_boundary(request, monkeypatch):
    if request.node.get_closest_marker("integration"):
        return
    def denied(*args, **kwargs):
        raise AssertionError("Unit tests must not access the network")
    original_connect = socket.socket.connect
    original_socketpair = socket.socketpair
    def local_socketpair(*args, **kwargs):
        # CPython Windows uses a loopback connection for its internal event-loop
        # wakeup pipe. Allow only the stdlib socketpair construction itself.
        with monkeypatch.context() as context:
            context.setattr(socket.socket, "connect", original_connect)
            return original_socketpair(*args, **kwargs)
    monkeypatch.setattr(socket, "socketpair", local_socketpair)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


@pytest.fixture
def fake_markdown():
    return (ROOT / "tests/fixtures/synthetic_fake.md").read_text(encoding="utf-8")


@pytest.fixture
def fake_parser(fake_markdown):
    class FakeParser:
        def parse(self, path):
            return ParsedDocument([{"fixture": "FAKE", "text": fake_markdown}], [fake_markdown], {"pipeline": "FAKE"})
    return FakeParser()


@pytest.fixture
def repo(tmp_path):
    Image.new("RGB", (50, 50), "white").save(tmp_path / "invoice.png")
    return tmp_path
