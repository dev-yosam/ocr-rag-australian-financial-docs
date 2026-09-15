"""Prepare upstream deployment assets locally; never starts Docker/services."""
from pathlib import Path
import hashlib
import json
import re
import secrets
import sys
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "deployment/ragflow"
TAG = "v0.27.2"
FILES = ["docker-compose.yml", "docker-compose-base.yml", "service_conf.yaml.template", "entrypoint.sh", "init.sql", ".env"]


def main() -> None:
    sources_path = DEST / "sources.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    upstream = DEST / "upstream"
    upstream.mkdir(exist_ok=True)
    for filename in FILES:
        target = upstream / ("env.template" if filename == ".env" else filename)
        if not target.exists():
            data = urllib.request.urlopen(f"https://raw.githubusercontent.com/infiniflow/ragflow/{TAG}/docker/{filename}", timeout=30).read()
            if hashlib.sha256(data).hexdigest() != sources["files"][filename]:
                raise ValueError("Upstream source checksum mismatch")
            target.write_bytes(data)
        if hashlib.sha256(target.read_bytes()).hexdigest() != sources["files"][filename]:
            raise ValueError("Local upstream source checksum mismatch")
    # Derive only the supported CPU / Elasticsearch / MySQL subset from official
    # configuration. No sandbox, MCP, Go server, model hosting, or new RAG engine.
    base = yaml.safe_load((upstream / "docker-compose-base.yml").read_text(encoding="utf-8"))
    primary = yaml.safe_load((upstream / "docker-compose.yml").read_text(encoding="utf-8"))
    names = ["es01", "mysql", "minio", "redis"]
    services = {name: base["services"][name] for name in names}
    services["ragflow-cpu"] = primary["services"]["ragflow-cpu"]
    volume_names = set()
    for name, service in services.items():
        service.pop("profiles", None)
        service["env_file"] = "./.env"
        service["logging"] = {"driver": "none"}
        if name != "ragflow-cpu":
            service.pop("ports", None)
        mounted = []
        for mount in service.get("volumes", []):
            source, target, *flags = mount.split(":")
            if source.startswith("./"):
                if source == "./ragflow-logs":
                    source = "../../.runtime/ragflow/logs"
                else:
                    source = "./upstream/" + source[2:]
            else:
                volume_names.add(source)
                source = "../../.runtime/ragflow/" + source
            mounted.append(":".join([source, target] + flags))
        service["volumes"] = mounted
    rag = services["ragflow-cpu"]
    rag["command"] = ["--init-model-provider-tables"]
    rag["depends_on"] = {name: {"condition": "service_healthy"} for name in names}
    rag["ports"] = ["127.0.0.1:9380:9380", "127.0.0.1:8080:80"]
    # Relative bind mounts work with Docker Desktop path translation as well as
    # WSL/Linux, and keep persistent service data inside this repository.
    for name in volume_names:
        (ROOT / ".runtime/ragflow" / name).mkdir(parents=True, exist_ok=True)
    (ROOT / ".runtime/ragflow/logs").mkdir(parents=True, exist_ok=True)
    compose = {"services": services, "networks": {"ragflow": {"driver": "bridge", "internal": True}}}
    (DEST / "docker-compose.yml").write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")
    env_path = DEST / ".env"
    if not env_path.exists():
        template = (upstream / "env.template").read_text(encoding="utf-8")
        values = {}
        for line in template.splitlines():
            if re.match(r"^[A-Z][A-Z0-9_]*=", line):
                key, value = line.split("=", 1)
                values[key] = value
        for key in values:
            if any(part in key for part in ("PASSWORD", "SECRET", "TOKEN", "API_KEY")):
                values[key] = secrets.token_hex(24) if "PASSWORD" in key or "SECRET" in key else ""
        values.update(RAGFLOW_IMAGE="infiniflow/ragflow:v0.27.2", DOC_ENGINE="elasticsearch",
                      DEVICE="cpu", COMPOSE_PROFILES="")
        env_path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    print("RAGFlow CPU deployment prepared; no services started; secrets not printed")


if __name__ == "__main__":
    main()
