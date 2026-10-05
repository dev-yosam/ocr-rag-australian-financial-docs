"""All model bytes in this file are FAKE synthetic fixtures, never real weights."""
import hashlib
import io
import json
import pytest

from app.core.errors import InputError
from app.llm import models


@pytest.fixture
def fake_model(tmp_path, monkeypatch):
    payloads = {name: b"FAKE SYNTHETIC MODEL FILE\n" for name in models.MODEL_FILES}
    payloads["config.json"] = b'{"model_type": "qwen3"}'
    payloads["tokenizer_config.json"] = b'{"fixture": "FAKE"}'
    payloads["model.safetensors.index.json"] = json.dumps({
        "weight_map": {f"FAKE.weight.{i}": name for i, name in enumerate(models.WEIGHT_FILES)}
    }).encode()
    lock = {
        "schema_version": 1, "repository": models.MODEL_REPOSITORY, "revision": "a" * 40,
        "files": {name: {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
                  for name, content in sorted(payloads.items())},
    }
    lock_path = tmp_path / models.LOCK_PATH
    lock_path.parent.mkdir()
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    calls = []

    def fake_download(url, destination):
        name = url.rsplit("/", 1)[-1]
        calls.append(url)
        destination.write_bytes(payloads[name])

    monkeypatch.setattr(models, "_download", fake_download)
    return tmp_path, payloads, lock, calls


def change_fake_lock(root, lock):
    (root / models.LOCK_PATH).write_text(json.dumps(lock), encoding="utf-8")


def deny_download(*args):
    raise AssertionError("Verification must not contact any network or SDK")


def test_prepare_pins_revision_whitelists_files_and_verifies_offline(fake_model, monkeypatch):
    root, payloads, lock, calls = fake_model
    directory, identity = models.prepare_model(root)
    assert directory == (root / models.MODEL_PATH).resolve()
    assert identity["repository"] == models.MODEL_REPOSITORY
    assert identity["revision"] == "a" * 40
    assert len(identity["lock_sha256"]) == 64
    assert len(calls) == len(models.MODEL_FILES)
    assert all(f"/resolve/{'a' * 40}/" in url for url in calls)
    assert {path.name for path in directory.iterdir()} == models.MODEL_FILES | {"manifest.json"}
    monkeypatch.setattr(models, "_download", deny_download)
    assert models.verify_model(root) == (directory, identity)
    assert models.model_directory(root) == directory
    assert models.model_identity(root) == identity
    assert models.prepare_model(root) == (directory, identity)
    assert models.prepare_model(root, verify_only=True) == (directory, identity)


def test_verify_only_missing_model_never_downloads(fake_model, monkeypatch):
    root, *_ = fake_model
    monkeypatch.setattr(models, "_download", deny_download)
    with pytest.raises(InputError, match="not prepared"):
        models.prepare_model(root, verify_only=True)
    assert not (root / models.MODEL_PATH).exists()


@pytest.mark.parametrize("name", ["config.json", "tokenizer.json", models.WEIGHT_FILES[0]])
def test_modified_model_files_are_rejected_even_with_existing_manifest(fake_model, name):
    root, *_ = fake_model
    directory, _ = models.prepare_model(root)
    target = directory / name
    original = target.read_bytes()
    target.write_bytes(b"!" + original[1:])  # Same byte count, different digest.
    with pytest.raises(InputError, match="checksum"):
        models.verify_model(root)


def test_missing_file_rejected(fake_model):
    root, *_ = fake_model
    directory, _ = models.prepare_model(root)
    (directory / "tokenizer.json").unlink()
    with pytest.raises(InputError, match="missing or checksum"):
        models.verify_model(root)


@pytest.mark.parametrize("change", ["revision", "files", "path", "lock_sha256"])
def test_manifest_cannot_redefine_trusted_model(fake_model, change):
    root, *_ = fake_model
    directory, _ = models.prepare_model(root)
    path = directory / "manifest.json"
    data = json.loads(path.read_text())
    data[change] = "MALICIOUS FAKE VALUE"
    path.write_text(json.dumps(data))
    with pytest.raises(InputError, match="manifest does not match"):
        models.verify_model(root)


@pytest.mark.parametrize("change", ["repository", "revision", "unsafe_file", "sha256", "size"])
def test_invalid_lock_fails_before_any_download(fake_model, change):
    root, _, lock, calls = fake_model
    if change == "repository":
        lock[change] = "untrusted/custom-model"
    elif change == "revision":
        lock[change] = "main"
    elif change == "unsafe_file":
        lock["files"]["../secret.py"] = lock["files"].pop("config.json")
    else:
        lock["files"]["config.json"][change] = "bad"
    change_fake_lock(root, lock)
    with pytest.raises(InputError, match="model lock"):
        models.prepare_model(root)
    assert calls == []


def test_corrupt_existing_file_is_not_overwritten(fake_model):
    root, _, _, calls = fake_model
    directory = root / models.MODEL_PATH
    directory.mkdir(parents=True)
    target = directory / "LICENSE"  # First sorted lock entry.
    target.write_bytes(b"FAKE CORRUPTION")
    with pytest.raises(InputError, match="checksum"):
        models.prepare_model(root)
    assert target.read_bytes() == b"FAKE CORRUPTION"
    assert not (directory / "manifest.json").exists()
    assert calls == []


def test_failed_download_never_publishes_manifest_or_final_file(fake_model, monkeypatch):
    root, *_ = fake_model

    def interrupted(url, destination):
        destination.write_bytes(b"FAKE PARTIAL")
        raise InputError("Download interrupted")

    monkeypatch.setattr(models, "_download", interrupted)
    with pytest.raises(InputError, match="interrupted"):
        models.prepare_model(root)
    directory = root / models.MODEL_PATH
    assert (directory / "LICENSE.download").exists()
    assert not (directory / "LICENSE").exists()
    assert not (directory / "manifest.json").exists()
    monkeypatch.setattr(models, "_download", deny_download)
    with pytest.raises(InputError, match="Incomplete"):
        models.prepare_model(root)


def test_download_hash_mismatch_is_not_renamed(fake_model, monkeypatch):
    root, *_ = fake_model
    monkeypatch.setattr(models, "_download", lambda url, path: path.write_bytes(b"FAKE WRONG MODEL"))
    with pytest.raises(InputError, match="checksum"):
        models.prepare_model(root)
    directory = root / models.MODEL_PATH
    assert not (directory / "LICENSE").exists()
    assert not (directory / "manifest.json").exists()


def test_verified_existing_files_are_reused_without_manifest(fake_model, monkeypatch):
    root, payloads, _, calls = fake_model
    directory = root / models.MODEL_PATH
    directory.mkdir(parents=True)
    for name, data in payloads.items():
        (directory / name).write_bytes(data)
    monkeypatch.setattr(models, "_download", deny_download)
    models.prepare_model(root)
    assert calls == []
    assert (directory / "manifest.json").is_file()


@pytest.mark.parametrize("extra", ["modeling_qwen.py", "pytorch_model.bin", "extra.json"])
def test_unexpected_files_rejected(fake_model, extra):
    root, *_ = fake_model
    directory, _ = models.prepare_model(root)
    (directory / extra).write_text("FAKE UNEXPECTED FILE")
    with pytest.raises(InputError, match="Unexpected"):
        models.verify_model(root)


def test_shard_index_cannot_point_outside_model(fake_model):
    root, payloads, lock, _ = fake_model
    name = "model.safetensors.index.json"
    payloads[name] = b'{"weight_map": {"FAKE": "../../private_inputs/receipt.json"}}'
    lock["files"][name] = {"sha256": hashlib.sha256(payloads[name]).hexdigest(), "size": len(payloads[name])}
    change_fake_lock(root, lock)
    with pytest.raises(InputError, match="shard index"):
        models.prepare_model(root)
    assert not (root / models.MODEL_PATH / "manifest.json").exists()


@pytest.mark.parametrize("name", ["config.json", "tokenizer_config.json"])
def test_remote_code_configuration_rejected(fake_model, name):
    root, payloads, lock, _ = fake_model
    payloads[name] = b'{"model_type": "qwen3", "auto_map": {"AutoModel": "remote.Model"}}'
    lock["files"][name] = {"sha256": hashlib.sha256(payloads[name]).hexdigest(), "size": len(payloads[name])}
    change_fake_lock(root, lock)
    with pytest.raises(InputError, match="Unsupported"):
        models.prepare_model(root)


def test_model_symlink_must_stay_in_model_directory(fake_model):
    root, *_ = fake_model
    directory, _ = models.prepare_model(root)
    source = directory / "tokenizer.json"
    external = root / "FAKE-outside-model.json"
    source.rename(external)
    try:
        source.symlink_to(external)
    except OSError:
        pytest.skip("Host does not permit symlink creation")
    with pytest.raises(InputError, match="escapes"):
        models.verify_model(root)


def test_downloader_does_not_use_sdk_token_or_environment_proxy(tmp_path, monkeypatch):
    calls = []

    class FakeOpener:
        def open(self, url, timeout):
            calls.append((url, timeout))
            return io.BytesIO(b"FAKE PUBLIC MODEL")

    def fake_opener(handler):
        assert isinstance(handler, models.urllib.request.ProxyHandler)
        assert handler.proxies == {}
        return FakeOpener()

    monkeypatch.setattr(models.urllib.request, "build_opener", fake_opener)
    target = tmp_path / "FAKE.download"
    models._download("https://huggingface.co/FAKE/resolve/revision/config.json", target)
    assert target.read_bytes() == b"FAKE PUBLIC MODEL"
    assert calls[0][1] == 120


def test_download_exception_text_is_sanitized(tmp_path, monkeypatch):
    class FakeOpener:
        def open(self, *args, **kwargs):
            raise RuntimeError("FAKE SECRET response and URL")

    monkeypatch.setattr(models.urllib.request, "build_opener", lambda *args: FakeOpener())
    with pytest.raises(InputError) as error:
        models._download("https://huggingface.co/FAKE", tmp_path / "FAKE.download")
    assert "SECRET" not in str(error.value)
