"""Explicit anonymous download of official PaddleX 3.6 model archives."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import ROOT
from app.core.files import contained, sha256, write_json

BASE = "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0"
MODELS = {"layout": "PP-DocLayoutV3", "recognition": "PaddleOCR-VL-1.6-0.9B"}
HF_REVISION = "c5630abae1d940eafe0697512a0325494b02ab42"
HF_FILES = ["LICENSE", "added_tokens.json", "chat_template.jinja", "config.json",
            "generation_config.json", "inference.yml", "model.safetensors",
            "preprocessor_config.json", "processor_config.json", "special_tokens_map.json",
            "tokenizer.json", "tokenizer.model", "tokenizer_config.json"]


def main() -> None:
    destination = contained(ROOT, ".models", must_exist=False)
    destination.mkdir(exist_ok=True)
    manifest_path = destination / "manifest.json"
    if manifest_path.exists():
        from app.paddleocr.worker import model_directories
        model_directories(ROOT)
        print("Existing model checksums verified")
        return
    lock_path = ROOT / "requirements/models.lock.json"
    locked = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    models = {}
    for role, name in MODELS.items():
        if role == "recognition":
            # Official BOS VL-1.6 archive returned 404 on 2026-09-11. Use the same
            # official model, at a pinned HF revision; no Hugging Face account/SDK.
            model = contained(ROOT, f".models/{name}", must_exist=False)
            model.mkdir(exist_ok=True)
            files = {}
            for filename in HF_FILES:
                path = model / filename
                url = f"https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/resolve/{HF_REVISION}/{filename}"
                if not path.exists():
                    partial = path.with_suffix(path.suffix + ".download")
                    with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as output:
                        shutil.copyfileobj(response, output, length=1024 * 1024)
                    partial.replace(path)
                files[filename] = sha256(path)
                if role in locked and locked[role]["files"].get(filename) != files[filename]:
                    raise ValueError("Model file differs from lock")
            models[role] = {"name": name, "path": model.relative_to(ROOT).as_posix(), "files": files}
            locked[role] = {"repository": "PaddlePaddle/PaddleOCR-VL-1.6", "revision": HF_REVISION, "files": files}
            print("Prepared recognition model")
            continue
        archive = contained(ROOT, f".models/{name}.tar", must_exist=False)
        url = f"{BASE}/{name}_infer.tar"
        if not archive.exists():
            partial = archive.with_suffix(".download")
            with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            partial.replace(archive)
        digest = sha256(archive)
        if role in locked and locked[role]["sha256"] != digest:
            raise ValueError("Downloaded archive differs from model lock")
        # Never allow archive links, special files, or paths outside .models.
        with tarfile.open(archive) as bundle:
            for member in bundle.getmembers():
                candidate = (destination / member.name).resolve()
                if not candidate.is_relative_to(destination.resolve()) or not (member.isfile() or member.isdir()):
                    raise ValueError("Unsafe archive member")
            bundle.extractall(destination, filter="data")
        model = contained(ROOT, f".models/{name}", must_exist=False)
        if not model.is_dir():
            alternative = contained(ROOT, f".models/{name}_infer", must_exist=False)
            if not alternative.is_dir():
                raise ValueError("Unexpected official model archive structure")
            model = alternative
        files = {p.relative_to(model).as_posix(): sha256(p) for p in model.rglob("*") if p.is_file()}
        if not files:
            raise ValueError("Empty model archive")
        models[role] = {"name": name, "path": model.relative_to(ROOT).as_posix(), "files": files}
        locked[role] = {"url": url, "sha256": digest}
        print(f"Prepared {role} model")
    write_json(lock_path, locked)
    write_json(manifest_path, {"pipeline_version": "v1.6", "models": models})
    print("VL-1.6 model manifest saved; processing can now run offline")


if __name__ == "__main__":
    main()
