# Implementation and validation record

## Current outcome

The local prototype now uses PaddlePaddle GPU inference (`paddlepaddle-gpu`
3.2.1, CUDA 12.9 package index) for PaddleOCR-VL. An earlier real PNG OCR run
confirmed its extracted total, but this is **not** complete M1 acceptance:
all-field accuracy, Docker runtime and live RAGFlow ingestion remain unverified
or previously blocked.

The current branch updates local extraction to the supplied 15-field TIRBIC
contract (`tirbic-15-v2`) and adds offline field evaluation. It is a breaking
schema change, not a new OCR model.
Latest unit result: **209 passed, 1 skipped, 2 deselected**, one upstream warning.
See `docs/TIRBIC_SCHEMA.md` for field meanings and provisional decisions.

The earlier scaffold and runtime records below are historical. The user has
since initialized Git and pushed the repository. The user explicitly authorized creation of `feat/update-labelling-standards`
from clean main at 53fef87 for this update. No stage, commit, push, merge or reset
was performed. Earlier branch-specific records below remain historical.

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
- Application dependency locks with package hashes, pinned GPU OCR requirements,
  model lock, official RAGFlow source hashes, GPU Docker recipes, README and
  persistent AGENTS rules.

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
  combination, using the GPU distribution of PaddlePaddle. No alternate OCR
  model or proprietary service was introduced.
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

1. Validate VL-1.6 GPU inference on each target host. Imports, CUDA discovery
   and model checksums alone are not complete acceptance. Docker validation still
   requires a working Docker daemon and NVIDIA container runtime.
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
requirements/ocr-gpu-cu129.txt
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


## Labelling standards update (2026-09-19)

- Read the complete one-page labelling-standards.pdf via text extraction and
  rendered visual review; also used the attached client-update screenshot.
- Source PDF SHA-256: `6e93f73a6a0afaa5c2f43c1f7a336aa77773ed2fce8b99177781b0bfb785ca0f`.
- Removed nature_of_expense; added supply_type (4 values) and expense_category
  (10 values). Contract is now tirbic-15-v2 with exactly 15 output fields.
- Added document title precedence and document-type-aware number selection,
  including reference fallback and exclusion of order/transaction numbers.
  User confirmed invoice-number priority for tax invoices; not an open question.
- Missing buyer_identity is an empty string; card-like candidates are rejected.
- Exact standalone includes-GST example maps to 100 per the supplied annotation
  convention; contradictory explicit percentages stay null. This is not a
  general claim about taxation or all documents mentioning GST.
- Added offline evaluation with field-specific normalization, Azure field-object
  handling and the missing-source/missing-value rule. Zero/false are real values.
  Buyer evaluation is gated by the reference >=1000 flag, not model prediction.
- Command: `.venv/Scripts/python.exe -m pytest -m "not integration" -q`.
  Result: 209 passed, 1 skipped (host symlink permissions), 2 deselected,
  1 existing Starlette/AnyIO deprecation warning.
- Extracted synthetic_fake.md locally into 15-field JSON, then ran
  scripts/evaluate_fields.py against the independently maintained synthetic
  expected.json: 15 correct / 15 evaluated. Report is in ignored
  outputs/labelling-synthetic-20260919-131242/evaluation.json.
  This validates rules/evaluation plumbing, not real OCR accuracy.
- Preserved merged GPU configuration/dependencies and did not run inference,
  install packages, contact Azure/RAGFlow, or process real financial documents.
- No 138-document evaluation or Label Studio migration was performed. New
  classifications still require explicit supported labels, not inferred semantics.


## CPU + GPU selection update (2026-09-19)

Branch: `feat/cpu-gpu-dual-mode`, based on `935354b`. No commit or push performed.
Local default is CPU; GPU remains explicit. Both use the same full VL-1.6 pipeline.

- `python -m pytest -m "not integration" -q`: 241 passed, 1 skipped (Windows
  symlink permission), 2 deselected; 1 existing Starlette/AnyIO deprecation warning.
- CPU `python scripts/check_environment.py`: actual Paddle 3.2.1 tensor computation
  and PaddleOCR 3.6.0 imports passed on Windows Python 3.13.7. No package installation
  or model download was needed.
- `python -m pip check`: no broken requirements.
- GPU preflight in this CPU environment: correctly exits 1 before model loading;
  no fallback. GPU contract tests use fakes, not actual GPU hardware.
- CPU hash lock restored from `a06d54d`; overlapping versions agree with app.lock.
  Fresh Linux installation was not tested. GPU recipe retains its existing CUDA
  12.9 index and direct version pins; transitive GPU dependencies are not locked.
- Compose configuration validated using repository-local empty Docker config.
  Updated GPU reservation syntax for compatibility with this Compose CLI.
- Docker daemon unavailable (docker_engine pipe missing); no image build, container
  inference, or actual GPU/Cetus deployment verified. Host settings unchanged.
- RAGFlow was not started or submitted to. No private documents processed.

- Real CPU OCR: `PADDLEOCR_DEVICE=cpu`, `PADDLEOCR_TIMEOUT_SECONDS=120`,
  `RUN_PADDLEOCR_INTEGRATION=1`, `python -m pytest -m paddleocr_integration -q`:
  1 failed after the explicit 120-second budget. This does not establish full OCR
  acceptance or accuracy. Inspect the ignored local manifest at
  `outputs/integration-9715a8ad27ec46b493c5d7faa65081ae/manifest.json`.
  The normal default timeout remains 1800 seconds. No success output was fabricated.


## Local POS matching update (2026-09-20)

- Added synthetic cases for POS timestamps, bill number context, GST label variants,
  customer-copy purchase totals, payment evidence and conflicting/invalid inputs.
- `python -m pytest -m "not integration" -q`: 254 passed, 1 skipped (Windows
  symlink permission), 2 integration tests deselected, existing AnyIO warning.
- Real user-provided photos were reviewed visually, not executed through OCR.
  No raw provider output was supplied for them; no end-to-end accuracy or full
  ground-truth score is claimed. No private data added to tracked tests/files.
- Legacy schema and percentage-unit differences remain evaluation blockers for a
  full 15-field comparison. Unlabelled sellers/classification remain unsupported.
- Changes remain uncommitted on the existing main branch; no branch switch,
  stage, commit, push or remote operation was performed.

## Local Qwen CPU / Cetus GPU implementation (2026-09-20)

Work remained on `feat/receipt-matching-rules`; existing POS-rule changes were
preserved. No stage, commit, push, branch switch or remote Git operation performed.

Implemented:

- Explicit `rules` / `llm` selection for the shared CLI/API pipeline; Qwen
  interprets OCR Markdown with the current 15-field definitions. The default
  remains `rules`. Python validates evidence/types/dates/amounts and recomputes
  the threshold flag. No rule fallback or cloud API.
- `app.cli extract` replays verified raw/Markdown artifacts into a new run
  without running OCR. Original source and artifact provenance are preserved.
  LLM request/response artifacts are private, hashed and retained on failure.
- Same Qwen/Qwen3-4B-Instruct-2507 source weights on both targets, revision
  `cdbee75f17c01a7cc42f958dc650907174af0554`. All 11 required files were downloaded
  explicitly and SHA-256 verified locally; three weight shards total
  8,044,982,000 bytes. No private receipt was sent to a model provider.
- Separate hash-pinned Windows Python 3.13 CPU and Linux Python 3.11 CUDA 12.6
  LLM locks, Transformers 4.57.6 / Torch 2.8.0 builds. The existing Paddle
  environment was not replaced. Full setup/replay/PBS instructions: `docs/LLM.md`.

Executed verification:

- `.venv\Scripts\python.exe -m pytest -m "not integration" -q`:
  **406 passed, 2 skipped, 3 deselected**, one existing Starlette/AnyIO warning.
  Both skips are unavailable Windows symlink creation. The LLM contract/runtime,
  model preparation, failure retention, API and replay tests use synthetic data
  and mocked providers; they are not real model accuracy evidence.
- Installed `requirements/llm-cpu.lock` in `.venv-llm` with hashes and binary-only
  distributions. Both `.venv` and `.venv-llm` `pip check` passed.
- `scripts/check_llm_environment.py`: actual Torch CPU tensor computation and
  Transformers imports passed with float32 and BF16. `--models` verified the
  complete local model. Requesting `gpu:0` in the CPU environment correctly
  exited 1 with no fallback. CPU float32 full inference was not measured.
- `RUN_LLM_INTEGRATION=1`, `LLM_DEVICE=cpu`, `LLM_DTYPE=bfloat16`,
  `LLM_TIMEOUT_SECONDS=1800`, `.venv\Scripts\python.exe -m pytest -m llm_integration -v`:
  **1 passed**, 379 deselected at the time of collection, one existing warning,
  **877.59 seconds (14m37s)**. This used the real pinned 4B model and handwritten
  synthetic OCR text. It did not run PaddleOCR or read a real photograph.
  Returned supplier `Example Test Services`, document number `SYN-004`, issue
  date `2026-08-27`, total 110 and GST 10; all 15 keys were validated. Unknown
  fields remained null/empty according to the schema. Additional core-field
  assertions were checked against the saved real response without rerunning
  inference. No OCR or general dataset accuracy claim follows.
- Worker metrics: 1,331 input tokens, 291 output tokens, 859.970 seconds inside
  generation (includes prompt processing; not a separate decode-speed benchmark),
  877.113 seconds including worker startup/model loading/checksums. Full model
  response and extracted result retained in
  `.runtime/llm-integration-900207b71e6144c2a2d2bed7d134cd5c/`.
- New token-progress reporting was checked with unit tests and a real Transformers
  tiny randomly initialized Qwen3 model. That API smoke test is not 4B accuracy
  evidence. The completed 4B run predates the progress-counter addition.
- `git diff --check` passed. PBS Bash syntax checked with `bash -n`; `.pbs` files
  enforce LF endings. Runtime, models, environment and output paths remain ignored.

Remaining deployment / evaluation work:

- The GPU lock was resolved for Linux x86_64 / glibc >= 2.28 / Python 3.11 but
  **not installed or executed on Cetus by this task**. Submit `scripts/cetus_llm.pbs`
  there to test the allocated GPU and the full OCR + Qwen path. GPU memory and
  latency remain unmeasured. Use FP16 for the Turing GPU; native BF16 is rejected.
- CPU BF16 works on this laptop but is slow even for the short synthetic input.
  This build is unquantized. A faster CPU deployment would need a separate
  evaluated optimization/quantization change; increasing a timeout is not a speedup.
- No new full real-photo OCR + LLM run or 15-field ground-truth dataset evaluation
  was performed. Evidence validation does not prove correct semantic matching.
- No new Docker image build, Qwen container deployment, RAGFlow live test,
  fine-tuning, API key configuration or host-setting change was performed.

## LLM 基本驗證與逐欄人工確認（2026-09-26）

使用者核准將來源證據問題改為人工確認事項。Qwen 繼續負責 15 欄配對；
Python 保留 JSON 結構、型別、日期、enum、有限金額與 AUD 限制的基本驗證。
`>=1000` 旗標仍依總額計算，其餘欄位不以舊 matching 規則、ground truth 或其他模型補值。

本次修改：

- `app/llm/contract.py`：新增 `ResponseAssessment`、`assess_response()` 與逐欄來源診斷。
  引文缺失、不存在或不支持候選值時保留合法欄位，輸出繁體中文確認事項。
  空白可折疊為一個空格，但不合併數字、不更改大小寫或標點。提示詞版本升為 v2，
  分類必須引用實際商品文字。缺值維持缺值；引文通過不代表語意正確。
- `app/llm/adapter.py`：保存 `review.json`、雜湊及 `passed_with_review`，保留模型原始回應。
- `app/pipeline.py`：CLI/API 共用結果包含 `status`、`requires_review`、review 摘要與
  artifact 路徑。待確認結果使用 `completed_needs_review`，仍產生 15 欄 `extracted.json`。
  總額若待確認，衍生門檻旗標也在 API/CLI 摘要列為待確認。
- `app/cli.py`：以中文呈現狀態、待確認欄位與檔案位置，不列印收據內容。
- `tests/unit/test_llm_contract.py`、`tests/unit/test_llm_pipeline.py`：新增／更新來源問題、
  空白正規化、分開數字、基本硬失敗、原值保留、API/CLI 狀態及 OCR 重用等回歸測試。
- `AGENTS.md`、`README.md`、`docs/LLM.md`：同步新行為與人工確認流程說明。

已執行：

```powershell
.venv\Scripts\python.exe -m pytest -m "not integration" -q
```

結果：**435 passed、2 skipped、3 deselected、1 warning**，3.65 秒。
兩項略過為 Windows 不允許建立 symlink；三項 integration 未選取。
警告為既有 Starlette/AnyIO 棄用警告。自動化資料與模型 worker 均為合成／fake，
單元測試通過不能當作模型準確率。

另用先前保存的真實收據 Qwen 回應進行本機「驗證邏輯重查」。先核對來源與舊 artifacts
雜湊，舊失敗紀錄維持不變，新結果寫入忽略的獨立 output 目錄：

- 新狀態為 `completed_needs_review`，輸出 `extracted.json`、`review.json` 及中文報告。
- GST／付款引文的換行差異不再阻擋輸出；分類與應稅比例仍列待確認。
- 消費日期仍為 `null`，沒有猜補。這是同一份舊模型回應在新版驗證器的行為，
  不是新提示詞的模型推論，也不能宣稱辨識準確率提高。
- 本次未重新執行 OCR、Qwen、Cetus/GPU、Docker 或 RAGFlow，也未重新下載模型。

`git diff --check` 通過。未 stage、commit、push、切換分支或修改遠端 Git。

## 單文件純 OCR 模式（2026-10-06）

本次範圍為使用者指定的第 1、2 項：完整 DocLayoutV3＋VL-1.6 解析，不執行 rules
或 Qwen；沒有 extracted.json 也能正常記錄 OCR 完成。工作分支為
`feat/ocr-only-diagnostics`。不新增批次、視覺化、YAML、API 路由或 Cetus 部署。

變更檔案與行為：

- `app/ocr_pipeline.py`：新增獨立 `OcrPipeline.parse()`。保留 provider raw 與
  Markdown，產生來源／artifact 雜湊、版本、裝置、耗時與獨立 OCR 狀態。
  `schema_version=ocr-run-v1`、`mode=ocr_only`、`extraction.status=not_requested`，
  `semantic_accuracy_verified=false`。空結果／頁數不一致不可標成完成；失敗保留已取得 raw。
- `app/cli.py`：新增 `parse SOURCE --run-id ID`，輸出中文狀態與三份 artifact 路徑。
- `app/core/config.py`：`from_ocr_env()` 只讀取 Paddle 裝置與等待上限，忽略 LLM、
  extractor 與 RAGFlow 設定。即使 LLM 設定無效，純 OCR 也不依賴它。
- `app/core/documents.py`／`app/pipeline.py`：共用既有輸入檢查，保留原格式與路徑限制。
  InvoicePipeline 的 rules／LLM 流程不變；可在後續新 run 重用純 OCR 的結果。
- `tests/unit/test_ocr_pipeline.py`：新增 22 項合成／fake 測試，覆蓋無 LLM 環境、
  禁止建構抽取器、CLI、環境隔離、頁面與原始資料保存、失敗／中斷、越界／損毀檔案、
  拒絕覆寫、雜湊與後續 re-extraction。
- `tests/integration/test_services.py`：新增 opt-in 真實單文件純 OCR 測試。
- `README.md`、`docs/DEMO_ZH_TW.md`、`AGENTS.md`：同步本階段行為與使用方式。

資料檢查：

- 使用者資料夾 `private_inputs/ocr_batch10` 共 10 份文件：6 張 JPG、4 份單頁 PDF。
- JPG 通過格式驗證與像素解碼；PDF 使用本機 PDFium 開啟並讀取頁數與尺寸。
- 全部符合既有檔案大小／圖片像素限制，SHA-256 均不同；資料夾已被 Git 忽略。
- 這只是輸入完整性檢查，尚未對這十份文件執行 OCR 或準確率評估；沒有上傳資料。

自動化驗證：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_ocr_pipeline.py -q
.\.venv\Scripts\python.exe -m pytest -m "not integration" -q
.\.venv\Scripts\python.exe -m app.cli parse --help
git diff --check
```

新增測試：**22 passed**。完整非 integration 測試：**457 passed、2 skipped、
4 deselected、1 warning**，4.85 秒。兩項跳過為 Windows symlink 權限限制；
既有 Starlette/AnyIO 棄用警告仍存在。四項 integration 未由這次 pytest 命令執行。

另已執行一次真實 CPU CLI 冒煙測試，與 fake 測試分開記錄：

- 在忽略的 `.runtime/ocr-only-smoke/synthetic.png` 產生 640×260 合成小圖，
  內容為 `SYNTHETIC OCR TEST`、`NOT VALID FOR PAYMENT`、`Total AUD 11.00`。
- 用 `parse` 執行完整 PaddleOCR-VL-1.6，`use_layout_detection=true`；
  PaddleOCR 3.6.0、PaddleX 3.6.0、PaddlePaddle CPU 3.2.1。
- 設定 `PADDLEOCR_TIMEOUT_SECONDS=300`、`OMP_NUM_THREADS=1`，並刻意將
  `INVOICE_EXTRACTOR=llm`、`LLM_PYTHON=.runtime/nonexistent-llm/python.exe`、
  `LLM_CPU_THREADS=INVALID_UNUSED_VALUE`，確認純 OCR 不讀取這些後段設定。
- 成功 run：`outputs/ocr_only_smoke_20261006_003247`，CLI 退出碼 0。
  目錄恰好只有 raw.json、parsed.md、manifest.json；來源與結果雜湊已核對。
- `status=completed`、`ocr_status=completed`、`page_count=1`，
  parser 初始化、辨識與結果處理合計 119.758 秒。Markdown 中三行測試內容均正確。
- 此結果只證明小型合成圖片的真實完整 OCR 與單文件輸出契約，不能代表十份文件的
  準確率或吞吐量，也不是大型合成 invoice 的 opt-in integration 測試。

未重新下載模型、未安裝套件、未執行 Qwen、未提交 Cetus 工作、未修改遠端或 Git 歷史。

## 2026-10-07：Gemini 3.5 Flash-Lite 雲端抽取（模擬驗證）

新增 `extract --extractor gemini`，重用已存 Paddle OCR；選擇
`gemini-3.5-flash-lite`，固定 Google GenerateContent HTTPS endpoint。
`--dry-run` 完全離線，不讀 key、不初始化 client，不要求 OCR／Qwen 環境。
`parse`、rules、Qwen 及 FastAPI 介面不變。沒有新增套件或改動 lock。

實作：

- `app/gemini/config.py`：Gemini 專屬設定，key 不出現在 repr／artifact。
- `app/gemini/contract.py`：選取原始逐頁 parsing blocks，含 header/footer 與表格；
  保留順序與座標、增加 block_ref，不傳本機路徑／圖像／其他 provider metadata。
  版本化 prompt 和 15 欄 structured-output schema；Python 不回填或改寫欄位。
- `app/gemini/client.py`：單次 HTTP 請求、key 只放 header、禁止 redirects／環境
  proxy／自動重試；檢查 HTTP、business error、封鎖、STOP、輸出內容及大小。
- `app/gemini/pipeline.py`：既有 OCR／來源 hash 核對、新目錄輸出、狀態／錯誤遮蔽；
  保存原始回答、獨立 validation/review，錯誤或截斷無 extracted.json。
- `app/cli.py`、`.env.example`、`AGENTS.md`、README、中文 demo、schema 文件同步；
  詳細操作於 `docs/GEMINI_ZH_TW.md`。AGENTS 的雲端例外限使用者明確選用 Gemini。

執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_gemini.py -q
.\.venv\Scripts\python.exe -m pytest -m "not integration" -q
.\.venv\Scripts\python.exe -m app.cli extract outputs/cetus_ti-photo-241_gpu_ocr_112612_hpc-head01 --extractor gemini --dry-run --run-id ti-photo-241_gemini_preview_20261007_032851
git diff --check
```

結果：

- 新增 **75 項**測試全數通過（0.87 秒），全部合成資料／fake HTTP，禁止真實網路。
  覆蓋 all-block 輸入、分頁／表格／header/footer、JSON number／null、精確型別、
  非法日期／enum／ABN、外幣、缺漏／重複 key、來源疑問、threshold 不回填、
  API contract、401/403/404/429/5xx、redirect、timeout、不重試、封鎖／截斷、
  thought 過濾、壞 response、大小限制、key 遮蔽、raw 保存、hash／路徑／覆寫限制、
  CLI／dry-run，以及與壞 Qwen/Paddle 設定隔離。
- 完整非 integration：**532 passed、2 skipped、4 deselected、1 warning**，5.27 秒。
  兩項跳過仍是 Windows 無 symlink 建立權限，warning 為既有 Starlette/AnyIO 棄用。
  首次新增測試執行因大型參數自動產生過長 pytest ID 而出現 fixture 錯誤；已改成
  明確短 ID，後續測試全部通過，無應用程式錯誤被忽略。
- 真實已存 Cetus `ti-photo-241` artifacts 的離線預覽完成，狀態 `prepared`，
  `network_attempted=false`；新目錄 `outputs/ti-photo-241_gemini_preview_20261007_032851`。
  這只驗證真實 Paddle 結構／provenance 可以接入，不是 Gemini 辨識結果。
- `git diff --check` 無 whitespace 錯誤；Windows LF/CRLF 提示不影響測試。

尚未驗證／限制：

- **沒有呼叫真實 Gemini API、沒有讀取／要求使用者提供 key、沒有上傳收據內容。**
  帳號模型權限、quota、費用與服務端 schema 接受情況須由 opt-in live run 確認；
  mock tests 不能證明雲端服務可用或欄位準確率。
- 證據檢查只確認 block_ref／原文引文存在，不判定語意支持。格式通過與 quote 存在
  均不代表正確，`semantic_accuracy_verified=false`，需與人工 ground truth 評估。
- 未新增 PP-Structure、批次、GPU 部署、RAGFlow 或 FastAPI 雲端 endpoint。
  重用 OCR 無需 GPU；Cetus 外網／API 政策未測，建議下載結果後於本機呼叫。
- 未跑原有四项 integration，未重新執行 OCR 或 Qwen，未安裝／下載模型，
  未 stage、commit、push、切換分支或改動 Git 歷史。

### 2026-10-07：首次 live HTTP 400 的診斷修正

使用者自行呼叫 `ti-photo-241_gemini_20261007_034509` 後收到 HTTP 400。
本機紀錄證實失敗在 request 階段，沒有 extracted.json；KEY_PRESENT 只證明
變數非空。舊 client 丟棄 Google error body，僅保存 http_400，因此無法從該 run
判定是 key 無效、API 設定或 request schema 問題，不宣稱已修好原始 400。

- 新增 `app/gemini/errors.py`，`client.py` 改用有界錯誤解析：只保存允許清單內的
  Google status/reason、已知 request 欄位與固定提示，不保存任意 provider message、
  key、project metadata 或文件內容。分類涵蓋 key 無效／過期／限制／外洩封鎖、
  服務未啟用、計費、project、schema／參數。不能辨識的仍明確保留未知錯誤。
- 新增 17 項合成錯誤測試，包括秘密／文件內容回顯、異常 details 型別、壞 JSON、
  過大 body、狀態保留與分類；Gemini 測試共 **92 passed**（1.31 秒）。
  完整非 integration 測試 **549 passed、2 skipped、4 deselected、1 warning**
  （4.21 秒）；跳過與 warning 原因同上，`git diff --check` 通過。
- 沒有更改模型、prompt、API request schema 或收據結果；沒有讀取 key，沒有由
  agent 重新送出 API 請求。等待使用者以同一終端明確重跑，取得新的安全診斷。

### 2026-10-07：明確選用 gemini-flash-lite-latest

- 依使用者要求，`GEMINI_MODEL=gemini-flash-lite-latest` 可選擇原本使用的 alias；
  未設定時維持 gemini-3.5-flash-lite。config 僅允許這兩個名稱，HTTPS host 不可改。
- client 從選定模型建立 endpoint；pipeline manifest 記錄請求名稱，以及 Google
  有回傳時的 `generation.model_version`。不更改 prompt／schema、不自動 fallback。
- 修改 config.py、client.py、pipeline.py、.env.example、AGENTS 與中文指南；新增
  6 項 synthetic/mock 測試，確認 alias endpoint、環境設定、版本記錄、拒絕非法
  模型及無 fallback。Gemini 測試共 **98 passed**（1.18 秒）。
- 未由 agent 讀取 key 或執行 live API；使用者需在已設定 key 的同一 PowerShell
  執行一次。不能宣稱改用 latest 已修好 HTTP 400；alias 也不是固定歷史模型版本。

### 2026-10-07：latest 仍 HTTP 400，新增不傳文件的連線檢查

使用者提供 `ti-photo-241_gemini_latest_20261007_035157`，其錯誤 artifact 仍為
http_400／error_body_unavailable。根因尚未確定；不再建議重送相同收據做診斷。

- `app/gemini/errors.py` 新增安全的 content_type、body_bytes、body_format 及
  read/parse failure 分類，支援 UTF-8 BOM；不保存任意 body 或 header 值。
- `app/gemini/diagnostics.py` 與 `scripts/check_gemini_environment.py` 提供一次
  官方 models.get 呼叫，只查選定模型 metadata。不讀文件、不帶 prompt/schema、
  不生成回答、不自動重試，不印 key／原始 provider 回覆。成功不等於推論驗收。
- 新增 11 項合成測試，涵蓋 HTML/BOM 診斷、GET URL／無 body、key 基本字元、
  錯誤遮蔽／無重試／timeout；Gemini 測試 **109 passed**（1.47 秒）。
- 未由 agent 呼叫 live API，未讀取使用者 key，原 HTTP 400 仍待新診斷結果確認。
