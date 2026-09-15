# Australian financial document pipeline — Milestone 1

Local-first processing of a **synthetic Australian tax invoice** using the full
PaddleOCR-VL-1.6 pipeline, conservative rule-based extraction, Pydantic validation,
and a RAGFlow HTTP integration boundary.

**Status: implementation is available; real end-to-end acceptance remains blocked.**
The application/unit tests and dependency checks run on Windows Python 3.13.7.
The real OCR attempt did not complete; RAGFlow live testing is blocked by an
unavailable Docker daemon. See `VALIDATION.md` for exact outcomes. Fake fixtures
are explicitly identified and are never presented as model output.

This directory was created as a new project. It was not cloned from GitHub,
contains no initialized Git history, and has no commits or remote modifications.

## Architecture

```text
Synthetic PNG/JPEG/PDF
    -> PaddleOCR subprocess (full VL-1.6 layout + recognition, no network)
    -> raw.json + normalized parsed.md
         -> independent rule extractor -> Pydantic -> extracted.json
         -> offline preparation -> optional self-hosted RAGFlow submission
```

RAGFlow alone owns document chunking, embeddings, vector storage, retrieval and
RAG orchestration. The application has no custom RAG engine. Q&A, fine-tuning,
bank statements, tax returns, UI, auth systems and production deployment are
outside Milestone 1.

`app/paddleocr` owns provider integration; `app/extraction` owns field extraction;
`app/schemas` owns validation; `app/rag` owns HTTP integration; `app/pipeline.py`
orchestrates artifacts. CLI and FastAPI use the same pipeline. No database or
task queue is required. Processing is synchronous and intended for one document
at a time, not concurrent production requests.

## Prerequisites and versions

- Reference runtime: Linux x86_64 / Python 3.11, preferably WSL2 + Docker Desktop.
- Windows Python 3.13.7 was used for dependency/import checks and unit tests.
- `paddleocr[doc-parser]==3.6.0`, `paddlex==3.6.0`, `paddlepaddle==3.2.1`.
- `PaddleOCRVL(pipeline_version="v1.6")`, with local PP-DocLayoutV3 and
  PaddleOCR-VL-1.6-0.9B model directories. No PP-OCR/PP-Structure substitution.
- FastAPI 0.141.1, Pydantic 2.13.5, pytest 9.1.1. Full transitive versions and
  distribution hashes are in `requirements/app.lock` and `requirements/ocr-cpu.lock`.
- RAGFlow v0.27.2 uses its own official container and Python runtime. Do not
  install RAGFlow into the application's Python environment.
- RAGFlow upstream requires at least 4 CPU cores, 16 GB RAM, 50 GB disk,
  Docker 24+, Compose 2.26.1+. Allow extra memory/storage for OCR and model archives.
- CPU inference is supported by the official documentation, but the performance
  of this selected stack on this host has not passed acceptance. No GPU is assumed.
- The optional `gpu:<index>` configuration does not install CUDA/GPU dependencies.
  A GPU installation requires a separately validated PaddlePaddle GPU environment;
  the supplied CPU lock and image are CPU-only.

The Python dependency lock was resolved for Python 3.11+ across platforms using
uv 0.8.22. Resolution is not proof that Linux runtime execution passed. Docker
builds and Linux imports could not be run on this host. Docker image tags and apt
repositories are not digest-locked; this is a reproducible development recipe,
not a bit-identical or production-hardened container supply chain.

## Installation

Run all commands from this project directory. Installation and model preparation
are explicit network-enabled steps. Never use an unpinned upgrade command.

PowerShell:

```powershell
python -m venv .venv
New-Item -ItemType Directory -Force .runtime/tmp, .cache/pip | Out-Null
$env:TEMP="$PWD/.runtime/tmp"
$env:TMP=$env:TEMP
.\.venv\Scripts\Activate.ps1
python -m pip --isolated install --index-url https://pypi.org/simple --cache-dir .cache/pip --require-hashes -r requirements/app.lock
python -m pip --isolated install --index-url https://pypi.org/simple --cache-dir .cache/pip --require-hashes -r requirements/ocr-cpu.lock
python -m pip --isolated check
python scripts/check_environment.py
```

WSL/Linux:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
mkdir -p .runtime/tmp .cache/pip
export TMPDIR="$PWD/.runtime/tmp"
python -m pip --isolated install --cache-dir .cache/pip --require-hashes -r requirements/app.lock
python -m pip --isolated install --cache-dir .cache/pip --require-hashes -r requirements/ocr-cpu.lock
python -m pip --isolated check
python scripts/check_environment.py
```

The OCR lock includes application/test dependencies. The separate application
lock allows unit tests without the heavy OCR libraries. Running from the root
does not require an editable install; `python -m app.cli` works directly. Avoid
reusing a Windows venv from WSL or vice versa.

## Model preparation and sample processing

### User-authorized private invoices

The user has authorized local OCR and field extraction on real invoice photos
they explicitly place in `private_inputs/`. This directory is ignored by Git and
excluded from Docker build context. Derived artifacts stay in ignored `outputs/`.
Do not run `rag prepare` or `rag submit` on these private runs; do not upload the
inputs or derived content to external services or use them as automated fixtures.
This is an exception to the synthetic-only development policy, not production
acceptance. The same current OCR timeout/runtime limitations still apply.

From an activated project venv, after placing a JPEG/PNG in that directory:

```powershell
$env:PADDLEOCR_DEVICE="cpu"
$env:PADDLEOCR_TIMEOUT_SECONDS="300"
python -m app.cli process "private_inputs/invoice_001.jpg" --run-id private-invoice-001
```

Use a new run ID each time. Check `manifest.json` in the run's output directory;
only a `completed` run has successfully produced validated extraction. Do not
paste private raw/Markdown/JSON contents into logs, issues, or chat.

### Synthetic development sample

```bash
python scripts/generate_sample_invoice.py
python scripts/prepare_models.py
python -m app.cli process samples/tax_invoices/sample_invoice.png --run-id sample_invoice
python -m app.cli rag prepare outputs/sample_invoice
```

These commands also work unchanged in activated PowerShell. If `sample_invoice`
already exists, use a new `--run-id`; existing results are never overwritten.

Preparation downloads only official public model assets, anonymously, without
the Hugging Face SDK or an account. The BOS VL archive returned 404 during
verification, so recognition files come from the **same official VL-1.6 model**
at Hugging Face revision `c5630abae1d940eafe0697512a0325494b02ab42`.
Layout uses the official PaddleX BOS PP-DocLayoutV3 archive. Python model code
from the Hugging Face repository is not downloaded or executed; inference uses
the pinned PaddleOCR/PaddleX implementation. Archive and file hashes are in
`requirements/models.lock.json`; cached files are rechecked before inference.

The sample is marked `SYNTHETIC - NOT VALID FOR PAYMENT`. Its supplier/customer
are fictional and its ABN is deliberately all zeroes, not a valid business ABN.
The independent expected result is in `samples/tax_invoices/expected.json`.

For a completed run:

```text
outputs/<run-id>/
  raw.json         # untouched provider JSON values, in page order
  parsed.md        # normalized Markdown, with explicit page boundaries
  extracted.json   # validated invoice, all nine keys, including nulls
  manifest.json    # source/artifact SHA-256, versions, status/failure stage
  ragflow.json     # created by rag prepare/submit
```

The manifest is written before processing. Partial pages are preserved on parser
failure. If no page was produced there is no fabricated raw/extracted output.
Worker stdout/stderr are discarded; errors retain only safe class/stage data.
Failed runs cannot be prepared for RAGFlow. A forced host termination can leave a
`processing` manifest; inspect it as an interrupted run, not a successful run.

## Extraction contract

- Keys: document_type, business_name, abn, invoice_number, invoice_date, subtotal,
  gst, total, currency. `document_type=tax_invoice`; default currency is AUD.
- Missing, conflicting, or unsafe-to-interpret fields are null. No inferred GST,
  arithmetic filling, confidence score, ABN lookup, or legal-validity claim.
- Supplier/customer labels are distinguished. Extraction accepts explicit labels
  in prose, Markdown table rows and simple HTML table rows. It is deliberately
  conservative; arbitrary invoice layouts may produce nulls.
- ABN and invoice identifiers remain strings. Only eleven-digit ABN shape is
  checked, not registration or checksum validity.
- Unambiguous dates become ISO dates. `03/04/2026` stays null. English month names,
  ISO dates and unambiguous numeric dates are supported.
- Amounts use finite Decimal, up to 18 digits including at most two decimal
  places. Decimal is serialized directly as JSON numbers via simplejson; no
  binary float conversion. NaN/Infinity and fractional cents are rejected.
- Explicit foreign currency is rejected for this AUD-only milestone.
- Pydantic validates shape/types, not the factual accuracy of OCR output.

## Local API

```bash
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

`GET /health` is liveness only (`ocr_readiness=not_checked`), not a model/service
readiness claim. `POST /v1/invoices/process` accepts:

```json
{"source":"samples/tax_invoices/sample_invoice.png"}
```

The response contains `run_id`, `invoice`, and repository-relative artifact paths.
Inputs must be repository-relative with forward slashes. Absolute paths, URLs,
parent traversal, Windows alternate data streams and resolved symlink/junction
escapes are rejected. Files are limited to 20 MiB; images to 25 megapixels. PDF
signature is checked before parsing; provider errors handle invalid/encrypted PDFs.
There is no URL fetching or arbitrary filesystem API. Bind only to loopback.

## Configuration

`.env.example` contains empty variable assignments only. The application reads
named process environment variables; it **does not automatically load `.env`**.
Set variables in your shell. Never print a populated environment/configuration.

| Variable | Default / purpose |
|---|---|
| PADDLEOCR_DEVICE | cpu; optional explicit gpu:index with separately validated runtime |
| PADDLEOCR_TIMEOUT_SECONDS | 1800; allowed 1–3600 seconds |
| RAGFLOW_BASE_URL | Empty; self-hosted service URL required for submit |
| RAGFLOW_API_KEY | Empty; local RAGFlow API credential required for submit |
| RAGFLOW_DATASET_ID | Empty; existing synthetic built-in-chunking dataset |
| RAGFLOW_TIMEOUT_SECONDS | 30; allowed >0 through 300 |
| RUN_PADDLEOCR_INTEGRATION | Only `1` enables the real model test |
| RUN_RAGFLOW_INTEGRATION | Only `1` enables the synthetic live upload test |

Only loopback, RFC1918/ULA private IP addresses and the documented Docker
hostnames are accepted for RAGFlow. HTTP proxies from environment are ignored;
redirects are disabled. Do not map allowed Docker hostnames to external services.

## RAGFlow deployment and ingestion

```bash
python scripts/prepare_ragflow.py
docker compose --env-file deployment/ragflow/.env -f deployment/ragflow/docker-compose.yml config --quiet
docker compose --env-file deployment/ragflow/.env -f deployment/ragflow/docker-compose.yml up -d
```

`prepare_ragflow.py` downloads/verifies six official v0.27.2 deployment assets
against `deployment/ragflow/sources.json`. It creates a CPU/Elasticsearch/MySQL
subset of upstream Compose, with MinIO and Redis. Changes from upstream:

- CPU only; no Go server, sandbox, MCP or separate admin server.
- Web/API ports bound to 127.0.0.1 (8080/9380); dependency ports unpublished.
- Private internal Docker network; persistent data bind-mounted below
  `.runtime/ragflow`, not unrelated host folders.
- Generated passwords stored only in ignored `deployment/ragflow/.env`.
- Docker log driver disabled. Upstream on-disk service logs stay under ignored
  `.runtime/ragflow/logs`; upstream logging behavior has not been live-audited.

This is a development stack, not a production deployment. Do not use real financial
documents. Starting Docker Desktop, installing WSL or modifying Linux
`vm.max_map_count` are outside-repository host operations and require separate
authorization. Do not perform those changes automatically.

Once running, create a local RAGFlow account and synthetic dataset in its own UI,
using its built-in chunking pipeline. Configure an already self-hosted embedding
provider accessible inside the private network. No paid/hosted embedding model is
configured here; model downloads/serving need separate explicit preparation.
Obtain a local API key and set the three RAGFLOW variables without sharing them
in chat. Then:

```bash
python -m app.cli rag prepare outputs/<completed-run-id>
python -m app.cli rag submit outputs/<completed-run-id>
```

Prepare is offline. Submit uploads Markdown, calls the built-in parse endpoint,
and queries status once. It does not wait for indexing completion or claim Q&A
works. `uploaded` and `processing` do not mean `completed`.

Upload uses `/api/v1/datasets/{id}/documents`; parsing uses
`/api/v1/datasets/{id}/chunks`. Datasets with an ingestion pipeline require a
different endpoint and are outside this M1 adapter contract. Responses are
checked for both HTTP errors and RAGFlow business `code` errors.

Submission intent is saved before upload. A second submit after any attempted
upload is rejected to prevent accidental duplicate documents. On timeout/failure,
inspect the local receipt and reconcile the document in the local RAGFlow UI;
there is no automatic deletion, retry or duplicate cleanup.

For future direct PDF parsing, RAGFlow supports a self-hosted PaddleOCR endpoint:
`PADDLEOCR_API_URL=http://host.docker.internal:8081/layout-parsing` and
`PADDLEOCR_ALGORITHM=PaddleOCR-VL`, with no PaddleOCR access token. The service
itself must run `pipeline_version=v1.6`; the algorithm label alone is not proof
of model version. This path is documented, not deployed or validated in M1.

## Docker application

```bash
docker compose build app
docker compose run --rm app python -m pytest -m "not integration"
docker compose run --rm app python -m app.cli process samples/tax_invoices/sample_invoice.png --run-id docker-sample
```

The application service has `network_mode: none`. Prepare models explicitly on
the host first. For the local HTTP API use the loopback host command above; the
default container service intentionally runs CLI jobs and publishes no ports.

## Tests and privacy

```bash
python -m pytest -m "not integration"
python -m pytest -m paddleocr_integration
python -m pytest -m ragflow_integration
```

Integration tests skip unless their RUN_* flag equals 1. When enabled they fail
on unavailable services/models, rather than silently skip. The RAGFlow integration
test leaves a clearly synthetic document in the configured dataset; it performs
no automatic deletion. Windows example for an explicit short diagnostic:

```powershell
$env:RUN_PADDLEOCR_INTEGRATION='1'
$env:PADDLEOCR_TIMEOUT_SECONDS='90'
python -m pytest -m paddleocr_integration
```

Each test invocation creates a unique temporary directory inside `.runtime`; old Windows sandbox directories are not reused. Unit fixtures explicitly say FAKE and require no external services. Tests cover
schema/nulls, Decimal JSON, extraction ambiguity, raw preservation, path containment,
provider contracts, API errors, offline preparation, and uncertain upload handling.
The OCR worker blocks Python socket connect/DNS/sendto calls; it is not an OS-level
sandbox for arbitrary native libraries. Use the no-network Docker service for
stronger network isolation. The project never invokes a hosted OCR/LLM API.

Logs must not contain document contents, API tokens, raw provider exceptions or
populated settings. Models and caches are under `.models`, `.cache`, `.runtime`.
Artifacts under `outputs` are local audit data, not logs, and are ignored by Git.
Never stage `.env`, runtime data or model files. Git history remains user-controlled.

## Official references

- [PaddleOCR 3.6.0 release](https://github.com/PaddlePaddle/PaddleOCR/releases/tag/v3.6.0)
- [VL usage and hardware support](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PaddleOCR-VL.html)
- [Pinned PaddleX pipeline configuration](https://github.com/PaddlePaddle/PaddleX/blob/v3.6.0/paddlex/configs/pipelines/PaddleOCR-VL-1.6.yaml)
- [Official VL-1.6 model](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6)
- [RAGFlow v0.27.2 deployment](https://github.com/infiniflow/ragflow/tree/v0.27.2/docker)
- [RAGFlow v0.27.2 HTTP API](https://ragflow.io/docs/v0.27.2/http_api_reference)
- [RAGFlow PaddleOCR self-hosting FAQ](https://ragflow.io/docs/faq)
- [Pydantic standard types and Decimal serialization](https://docs.pydantic.dev/latest/api/standard_library_types/)
