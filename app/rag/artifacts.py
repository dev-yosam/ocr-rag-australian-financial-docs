from pathlib import Path

from app.core.config import Settings
from app.core.errors import InputError, RagFlowError
from app.core.files import contained, read_json, sha256, write_json
from app.rag.client import RagFlowClient


def prepare(root: Path, relative: str) -> dict:
    directory = contained(root, relative)
    manifest = read_json(contained(root, f"{relative}/manifest.json"))
    markdown = contained(root, f"{relative}/parsed.md")
    if manifest.get("status") != "completed":
        raise InputError("Only completed runs may be prepared")
    if sha256(markdown) != manifest.get("artifacts", {}).get("parsed.md"):
        raise InputError("Markdown checksum mismatch")
    source = contained(root, manifest["source"])
    if sha256(source) != manifest.get("source_sha256"):
        raise InputError("Source checksum mismatch")
    payload = {"status": "prepared", "source": manifest["source"],
               "source_sha256": manifest["source_sha256"],
               "markdown": markdown.relative_to(root).as_posix(), "markdown_sha256": sha256(markdown)}
    target = contained(root, f"{relative}/ragflow.json", must_exist=False)
    if target.exists():
        existing = read_json(target)
        if any(existing.get(key) != payload[key] for key in ("source_sha256", "markdown_sha256", "markdown")):
            raise InputError("Existing RAGFlow preparation differs")
        return existing
    write_json(target, payload)
    return payload


def submit(settings: Settings, relative: str, client: RagFlowClient) -> dict:
    record = prepare(settings.root, relative)
    target = contained(settings.root, f"{relative}/ragflow.json")
    if record["status"] != "prepared":
        raise RagFlowError("Submission already attempted; reconcile the saved receipt before retrying")
    # Save an intent before sending. Even uncertain/timeout outcomes cannot cause
    # an accidental duplicate on a second CLI invocation.
    record.update(status="submission_pending", dataset_id=settings.ragflow_dataset_id)
    write_json(target, record)
    markdown = contained(settings.root, record["markdown"])
    document_id = client.upload_markdown(settings.ragflow_dataset_id, f"{target.parent.name}.md", markdown.read_bytes())
    record.update(status="uploaded", document_id=document_id)
    write_json(target, record)
    client.start_parsing(settings.ragflow_dataset_id, document_id)
    record["status"] = "processing"
    write_json(target, record)
    record["status"] = client.get_status(settings.ragflow_dataset_id, document_id)
    write_json(target, record)
    return record
