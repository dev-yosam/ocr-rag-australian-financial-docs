from datetime import date
import hashlib
from pathlib import Path
import re

import simplejson

from app.core.errors import InputError


def contained(root: Path, relative: str, *, must_exist: bool = True) -> Path:
    path = Path(relative)
    if path.is_absolute() or path.drive or ":" in relative or "\\" in relative:
        raise InputError("Use a repository-relative path with forward slashes")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise InputError("Path escapes repository")
    if must_exist and not resolved.exists():
        raise InputError("Input does not exist")
    return resolved


def new_run(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run_id):
        raise InputError("Invalid run ID")
    path = contained(root, f"outputs/{run_id}", must_exist=False)
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise InputError("Output run already exists; choose a new run ID") from None
    return path


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_text(value: object) -> str:
    def default(item: object) -> str:
        if isinstance(item, date):
            return item.isoformat()
        raise TypeError("Unsupported JSON type")
    return simplejson.dumps(value, use_decimal=True, allow_nan=False,
                            ensure_ascii=False, indent=2, default=default) + "\n"


def write_json(path: Path, value: object) -> None:
    text = json_text(value)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> object:
    try:
        return simplejson.loads(path.read_text(encoding="utf-8"), use_decimal=True)
    except (ValueError, OSError):
        raise InputError("Invalid artifact JSON") from None
