# Implementation and validation record

## Current outcome

The local prototype has completed one real PNG CPU OCR run (2026-09-16).
The user confirmed its extracted total. This is **not** complete M1 acceptance:
all-field accuracy, synthetic ground-truth OCR acceptance, GPU execution, Docker
runtime and live RAGFlow ingestion remain unverified or previously blocked.

The current branch updates local extraction to the supplied 14-field TIRBIC
contract (`tirbic-14-v1`). It is a breaking schema change, not a new OCR model.
Latest unit result: **124 passed, 1 skipped, 2 deselected**, one upstream warning.
See `docs/TIRBIC_SCHEMA.md` for field meanings and provisional decisions.

The earlier scaffold and runtime records below are historical. The user has
since initialized Git and pushed the repository. This implementation turn made
no Git mutations and stayed on the user's `feat/align-receipt-schema` branch.

## Schema update verification (2026-09-16)

- Updated schema/extractor, CLI/API assertions and independent synthetic expected
  JSON; added synthetic cases for all 14 fields, date separation, tables, adjacent
  lines, seller/buyer context, threshold boundaries, percentages and strict bools.
- Command: `.venv/Scripts/python.exe -m pytest -m "not integration" -q`.
- Result: 114 passed, 1 skipped (Windows symlink creation unavailable),
  2 deselected (external integration), 1 Starlette/AnyIO deprecation warning.
- Existing private PNG Markdown was re-extracted locally without running OCR or
  uploading anything. The review JSON has total_cost and its derived >=1000 flag;
  the other 12 fields remain null. This does NOT demonstrate improved accuracy
  on that private image. Further layout interpretation remains necessary.
- The private review is under ignored outputs/schema-review-d42839e18c4a, with
  source/output hashes in review.json. It is not a new OCR run or RAG artifact.
  Existing OCR raw/Markdown/JSON files were not overwritten.
- Threshold uses >=1000 provisionally. Ambiguous dates, partial payment, mixed
  nature and unsupported taxable-extent inference remain null. Client review
  of these choices is outstanding.
- OCR dependencies/model weights and deployment configuration are unchanged.

## Delivered behavior

- Independent parser, normalization, extraction, schema and RAGFlow layers.
- Shared CLI/FastAPI processing; safe errors; relative path containment.
- Explicit VL-1.6 selection, local model paths, per-file checksum verification,
  subprocess network guard, timeout and Windows process-tree cleanup.
- Raw provider pages retained before Markdown conversion; failed runs recorded;
  completed run directories cannot be overwritten.
- Conservative labels, supplier/customer distinction, null ambiguity, date
  normalization, Decimal amounts and numeric JSON serialization.
- Offline RAGFlow preparation; local-only submission; separate HTTP/business-code
  validation; uncertain upload receipts prevent automatic duplicate retries.
- Synthetic PNG, independent expected JSON and explicitly fake unit fixture.
- Full transitive dependency locks with package hashes, model lock, official
  RAGFlow source hashes, CPU Docker recipes, README and persistent AGENTS rules.

## Historical baseline commands and observed results

Commands were run using the project-local `.venv/Scripts/python.exe` on Windows
Python 3.13.7. Results below reflect the original baseline, before the 14-field schema update.

| Check | Result |
|---|---|
| `python -m pytest -m "not integration"` | **61 passed, 1 skipped, 2 deselected** |
| Symlink containment test | Skipped: this host denied symlink creation; traversal/absolute-path tests passed |
| Dependency check: `python -m pip --isolated check` | Passed: no broken requirements |
| `python scripts/check_environment.py` | Passed: PaddleOCR 3.6.0, PaddleX 3.6.0 and PaddlePaddle 3.2.1 imported |
| `python scripts/generate_sample_invoice.py` | Passed: synthetic PNG created |
| `python scripts/prepare_models.py` | Passed: both models downloaded and checksummed |
| `python scripts/prepare_ragflow.py` | Passed: pinned upstream assets and local CPU configuration prepared; no services started |
| Application Compose `config --quiet` | Passed |
| RAGFlow Compose `config --quiet` with its private env file | Passed |
| Real OCR integration, opt-in enabled and timeout=90 seconds | **1 failed** after about 92 seconds; manifest records `pipeline_initialization` / `WorkerExitOrTimeout` |
| Earlier real sample attempt | Interrupted after prolonged lack of completed pages; recorded failed |
| `python -m pytest -m ragflow_integration` | 1 skipped: live service/dataset credentials not configured |
| Docker daemon version probe | Failed: Docker engine named pipe unavailable |
| Git initialization check | `.git` absent |

One non-failing upstream Starlette/AnyIO deprecation warning remains. During
testing, older sandbox-created temporary/cache directories became inaccessible
under Windows ACLs. The test configuration now uses a new project-local directory
for every invocation and disables pytest's shared cache; the normal command above
passed after that change. No existing directory permissions were broadened.

The real OCR test was run with:

```powershell
$env:RUN_PADDLEOCR_INTEGRATION='1'
$env:PADDLEOCR_TIMEOUT_SECONDS='90'
python -m pytest -m paddleocr_integration
```

Its source and failed manifest remain locally under `outputs/`. There is no
successful `outputs/sample_invoice/extracted.json`. Unit-generated artifacts are
under ignored `.runtime` directories and explicitly identify their parser as FAKE.

## Compatibility and source decisions

- Preserved the approved PaddleOCR 3.6.0 / PaddleX 3.6.0 / PaddlePaddle 3.2.1
  combination. No alternate OCR model or proprietary service was introduced.
- Official BOS VL-1.6 archive returned 404. The recognition weights instead use
  official `PaddlePaddle/PaddleOCR-VL-1.6` at revision
  `c5630abae1d940eafe0697512a0325494b02ab42`. The model identity did not change.
- Requirements were resolved with uv 0.8.22 across Python/platform markers and
  installed on Windows. Linux/Python 3.11 runtime execution is still unverified.
- RAGFlow Compose derives from six upstream v0.27.2 assets, with CPU-only service
  selection, local bind mounts, loopback ports and an internal network. Exact
  source hashes are in `deployment/ragflow/sources.json`.
- Local generated deployment passwords are only in ignored `.env`; they are not
  included in source manifests, reports or logs. No personal credentials were used.

## Remaining blockers and next acceptance step

1. Diagnose VL-1.6 CPU pipeline initialization on a usable supported runtime.
   Imports and model checksums alone are not inference success. The supplied
   Linux/Python 3.11 container is the next reference environment; building/running
   it requires a working Docker daemon. GPU setup is not assumed or installed.
2. Run the synthetic invoice successfully and compare every extracted field with
   the independent expected JSON. Preserve real raw and Markdown artifacts.
3. Start the self-hosted RAGFlow development stack, configure a local embedding
   provider and synthetic dataset, then enable its integration test. A live upload
   must not be described as completed indexing until status confirms completion.
4. Re-run symlink/junction containment tests on a host where links can be created.

Host changes (Docker Desktop startup/installation, WSL installation, kernel
configuration) were not authorized as part of repository-only implementation and
were not performed. No paid service, financial-document upload or account login
was used to bypass these blockers.

## Review files

All source files are new. The inventory below excludes virtual environments,
downloaded models, caches, private `.env`, runtime output and upstream cache copies.

```text
.dockerignore
.env.example
.gitignore
AGENTS.md
Dockerfile
README.md
VALIDATION.md
app/__init__.py
app/api/__init__.py
app/api/main.py
app/cli.py
app/core/__init__.py
app/core/config.py
app/core/errors.py
app/core/files.py
app/extraction/__init__.py
app/extraction/invoice.py
app/paddleocr/__init__.py
app/paddleocr/adapter.py
app/paddleocr/normalize.py
app/paddleocr/types.py
app/paddleocr/worker.py
app/pipeline.py
app/rag/__init__.py
app/rag/artifacts.py
app/rag/client.py
app/schemas/__init__.py
app/schemas/invoice.py
compose.yaml
deployment/ragflow/docker-compose.yml
deployment/ragflow/sources.json
pyproject.toml
requirements/app.lock
requirements/models.lock.json
requirements/ocr-cpu.lock
samples/tax_invoices/expected.json
samples/tax_invoices/sample_invoice.png
scripts/check_environment.py
scripts/generate_sample_invoice.py
scripts/prepare_models.py
scripts/prepare_ragflow.py
tests/__init__.py
tests/conftest.py
tests/fixtures/synthetic_fake.md
tests/integration/test_services.py
tests/unit/test_adapters.py
tests/unit/test_cli.py
tests/unit/test_invoice.py
tests/unit/test_pipeline.py
```


## Local OCR timeout diagnosis (2026-09-15)

- The adapter now distinguishes timeout, interruption, and normal process exit,
  recording return code, elapsed monotonic seconds, configured timeout and last
  provider stage. Provider stdout/stderr remain suppressed.
- User-authorized private photo was processed locally only; no RAG submission.
- Run `private-diagnostic-20260915-231555`: failed with `WorkerTimeout`,
  termination `timeout`, stage `parsing`, return code 1 after forced termination.
  Configured timeout: 600 seconds; observed monotonic elapsed: 2012.999 seconds.
  Scheduling/suspension may affect the difference; this is not a pure inference
  benchmark and the exact host cause was not established.
- Model initialization completed, but no full page was returned. Only the failed
  manifest exists. No OCR accuracy or end-to-end success is claimed.
- `python -m pytest -m "not integration" -q`: 67 passed, 1 skipped
  (host cannot create symlinks), 2 deselected, 1 upstream AnyIO deprecation warning.
- Changed source/tests: app/paddleocr/adapter.py, tests/unit/test_adapters.py,
  tests/unit/test_cli.py. No dependency or model changes and no Git mutations.


## Follow-up: joined title and ABN diagnosis (2026-09-16)

- Diagnosed OCR structure locally without printing source values. The saved text
  contains a standalone document heading joined to an explicitly labelled ABN.
- Added a narrow split rule plus 10 synthetic regression cases covering separator
  variants, malformed/unlabelled numbers, trailing text, conflicting values,
  buyer context and a heading in an HTML cell.
- `.venv/Scripts/python.exe -m pytest -m "not integration" -q`:
  124 passed, 1 skipped (symlink permission), 2 deselected, 1 upstream warning.
- Re-extraction from existing Markdown populated document_type and seller_abn
  in addition to total_cost and its derived >=1000 flag. Ten fields remain null.
  Total is unchanged. Newly matched values have NOT been visually verified
  against the source image. This is extraction coverage, not measured accuracy.
- Private artifacts: outputs/schema-diagnosis-3b1dcafb4162/extracted.json,
  diagnostics.json and review.json. These are extraction-only review artifacts,
  not a fresh OCR run, shared test fixture or permitted RAG submission.
- No model, runtime, GPU, dependency or Git changes were made in this follow-up.
