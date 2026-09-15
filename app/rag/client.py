import ipaddress
import re
from urllib.parse import urlsplit

import httpx

from app.core.errors import RagFlowError


def safe_base_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if parsed.port is not None and not 0 < parsed.port <= 65535:
            raise ValueError
    except ValueError:
        raise RagFlowError("Invalid self-hosted RAGFlow URL") from None
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise RagFlowError("Invalid self-hosted RAGFlow URL")
    host = parsed.hostname.lower()
    if host not in {"localhost", "ragflow", "host.docker.internal"}:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise RagFlowError("Use a private IP, localhost, or the documented Docker hostname") from None
        networks = [ipaddress.ip_network(x) for x in
                    ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "::1/128", "fc00::/7")]
        if not any(address in network for network in networks):
            raise RagFlowError("External RAGFlow destinations are not permitted")
    return url.rstrip("/")


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise RagFlowError("Invalid RAGFlow identifier")
    return value


class RagFlowClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 30,
                 transport: httpx.BaseTransport | None = None):
        base_url = safe_base_url(base_url)
        if not api_key:
            raise RagFlowError("Self-hosted RAGFlow API key is required")
        self.client = httpx.Client(base_url=base_url, timeout=timeout, trust_env=False,
                                  follow_redirects=False, transport=transport,
                                  headers={"Authorization": f"Bearer {api_key}"})

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise RagFlowError("RAGFlow request failed; response details suppressed") from None
        if not isinstance(body, dict) or type(body.get("code")) is not int or body["code"] != 0:
            raise RagFlowError("RAGFlow reported an application error")
        return body.get("data")

    def upload_markdown(self, dataset_id: str, name: str, content: bytes) -> str:
        data = self._request("POST", f"/api/v1/datasets/{identifier(dataset_id)}/documents",
                             files={"file": (name, content, "text/markdown")})
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise RagFlowError("Unexpected RAGFlow upload response")
        document_id = data[0].get("id")
        if not isinstance(document_id, str):
            raise RagFlowError("Unexpected RAGFlow document identifier")
        return identifier(document_id)

    def start_parsing(self, dataset_id: str, document_id: str) -> None:
        self._request("POST", f"/api/v1/datasets/{identifier(dataset_id)}/chunks",
                      json={"document_ids": [identifier(document_id)]})

    def get_status(self, dataset_id: str, document_id: str) -> str:
        data = self._request("GET", f"/api/v1/datasets/{identifier(dataset_id)}/documents",
                             params={"id": identifier(document_id)})
        if not isinstance(data, dict) or not isinstance(data.get("docs"), list):
            raise RagFlowError("Unexpected RAGFlow status response")
        docs = [d for d in data["docs"] if isinstance(d, dict) and d.get("id") == document_id]
        if len(docs) != 1:
            raise RagFlowError("RAGFlow document not found")
        state = str(docs[0].get("run"))
        states = {"0": "uploaded", "1": "processing", "2": "cancelled", "3": "completed", "4": "failed"}
        if state not in states:
            raise RagFlowError("Unknown RAGFlow processing state")
        return states[state]
