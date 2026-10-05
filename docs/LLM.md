# Local Qwen extraction: Windows CPU and Cetus GPU

This adds a second extraction strategy. PaddleOCR still runs the complete
PP-DocLayoutV3 + PaddleOCR-VL-1.6-0.9B pipeline. Qwen reads its normalized Markdown
and assigns the 15 TIRBIC fields. It does not receive the original image or raw
bounding boxes. Python checks the output contract and calculates the existing
`total_cost >= 1000` flag. There is no cloud LLM API, key, training or RAG change.

欄位配對由 Qwen 負責，Python 保留基本格式驗證與逐欄來源檢查。來源證據有疑問時，
保留格式合法的欄位值，另寫入 `review.json` 供人工確認；不再僅因引文不符就擋下
整張文件。LLM 模式不使用舊 matching 規則補值。此行為在本機 CPU 與 Cetus GPU
共用同一份程式；已安裝 LLM 環境及準備權重的主機更新程式即可，不需重新下載模型。

**Measured status (2026-09-20):** one real Qwen run on this Windows CPU using
BF16 passed the synthetic OCR-text test in 877.59 seconds (14m37s). Its input
had 1,331 tokens including instructions and its response had 291 tokens.
This verifies the LLM step, not real-photo accuracy or GPU deployment. The
Cetus script remains ready for a user-submitted GPU test.

```text
image -> PaddleOCR subprocess -> raw.json + parsed.md
                                    |
                                    v
                         Qwen subprocess (CPU or GPU)
                                    |
                          15 values + quoted evidence
                                    |
                         Python 基本驗證 + 來源檢查
                                    |
                         extracted.json + review.json
```

The OCR subprocess exits before Qwen loads, allowing their GPU memory allocations
to be released between stages. This is a single-document prototype, not a
persistent model server. Every request loads the model again.

## What stays the same across computers

| Item | Windows laptop | Cetus compute node |
| --- | --- | --- |
| Source weights | Qwen/Qwen3-4B-Instruct-2507 | Same repository and revision |
| Revision | `cdbee75f17c01a7cc42f958dc650907174af0554` | Same |
| OCR/app environment | Existing `.venv`, Paddle CPU | Existing `.venv-gpu`, Paddle CUDA 12.9 |
| Text-LLM environment | New `.venv-llm`, Python 3.13, Torch 2.8.0+cpu | New `.venv-llm`, Python 3.11, Torch 2.8.0+cu126 |
| Transformers | 4.57.6 | 4.57.6 |
| Device selection | `LLM_DEVICE=cpu` | `LLM_DEVICE=gpu:0` |
| Automatic dtype | float32 | float16 |

These are separate Python environments. Do not install either LLM lock into the
Paddle environment, copy a Windows environment to Linux, or install both Torch
builds in one environment. Torch's CUDA 12.6 libraries are independent of the
existing Paddle CUDA 12.9 libraries because the workers run in different processes.
The NVIDIA driver must support both. GPU compatibility must be tested in a PBS
allocation; package installation alone does not prove it works.

Same source weights do not guarantee identical CPU/GPU values or accuracy.
Different dtypes and kernels can change output. Generation is greedy, with no
sampling, but semantic correctness still needs reviewed ground truth.

The weight files occupy approximately 8 GB. Float32 weights alone need roughly
16 GB RAM; BF16/FP16 weights roughly 8 GB, plus loading, activations and cache.
Those are storage estimates, not measured peak usage. Leave additional headroom.
CPU `bfloat16` is an explicit lower-memory option and can be slow on CPUs without
native BF16 acceleration. The Cetus Quadro RTX 6000 uses `float16`; do not choose
`bfloat16` on that Turing GPU. This implementation uses eager attention, not
FlashAttention, bitsandbytes or automatic device fallback.

## 1. Install the additional environment on Windows

Run commands in PowerShell from the repository root. The existing OCR `.venv`
must already work and use Python 3.13 for this Windows-specific lock. Each line
below is a complete command. No activation is required when using these paths.

```powershell
.\.venv\Scripts\python.exe -m venv .venv-llm
New-Item -ItemType Directory -Force .runtime/tmp, .cache/pip-llm | Out-Null
$env:TEMP="$PWD/.runtime/tmp"
$env:TMP=$env:TEMP
.\.venv-llm\Scripts\python.exe -m pip --isolated install --require-hashes --only-binary=:all: --cache-dir .cache/pip-llm -r requirements/llm-cpu.lock
.\.venv-llm\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/prepare_llm.py
$env:LLM_DEVICE="cpu"
.\.venv-llm\Scripts\python.exe scripts/check_llm_environment.py --models
```

Installation and `prepare_llm.py` are the only network-enabled setup steps.
Preparation downloads the pinned model anonymously, verifies every SHA-256 and
writes a manifest under `.models/llm/Qwen3-4B-Instruct-2507/`. Running preparation
again verifies complete files without downloading them. `--verify-only` never
downloads. An incomplete `.download` file or bad hash fails explicitly; after
the downloader has stopped, remove only the reported partial file and rerun
preparation. Do not delete the environment or the complete model shards.

During processing, local-only loading, offline flags and a Python socket audit
guard prevent automatic model fetches. Missing weights fail; they are never
downloaded automatically. These safeguards do not replace OS network isolation
when a deployment requires a formal network boundary.

## 2. Try Qwen without rerunning OCR

Choose an existing run directory containing `manifest.json`, `raw.json` and
`parsed.md`. Substitute its actual name for `outputs/your_previous_run`:

```powershell
$env:LLM_DEVICE="cpu"
$env:LLM_DTYPE="bfloat16"
$env:LLM_TIMEOUT_SECONDS="3600"
.\.venv\Scripts\python.exe -m app.cli extract outputs/your_previous_run --extractor llm
```

This creates a new randomly named run and prints its name. To choose your own,
append `--run-id qwen_test_01`; choose a different ID next time. Existing runs
are never overwritten. Replay checks the original raw/Markdown hashes and
source provenance, copies the OCR artifacts, and records the previous manifest
hash. It does not load Paddle or require the original image to still exist.
Hashes detect mismatch against the saved manifest, not malicious rewriting of
both the artifacts and manifest.

For a complete new image run (both OCR and Qwen):

```powershell
$env:PADDLEOCR_DEVICE="cpu"
$env:PADDLEOCR_TIMEOUT_SECONDS="3600"
.\.venv\Scripts\python.exe -m app.cli process samples/tax_invoices/sample_invoice.png --extractor llm
```

`scripts/prepare_models.py` must have prepared the OCR weights beforehand.
You can substitute a repository-relative authorized image path, such as
`private_inputs/my_receipt.png`. Large images can still exceed the OCR timeout;
using Qwen does not accelerate the OCR stage or recover text it failed to read.

To compare the baseline on identical OCR, run:

```powershell
.\.venv\Scripts\python.exe -m app.cli extract outputs/your_previous_run --extractor rules
```

## 3. Set up the LLM on Cetus

First bring this source change to Cetus using your normal review/push/pull
workflow. These instructions do not perform Git operations. Run from the Cetus
repository root. Do not copy the Windows `.venv-llm` directory.

Using the Miniforge installation already created for this project:

```bash
mkdir -p .runtime/tmp .cache/conda .cache/pip-llm
export TMPDIR="$PWD/.runtime/tmp"
export CONDA_PKGS_DIRS="$PWD/.cache/conda"
.runtime/miniforge3-retry/bin/conda create -y -p "$PWD/.venv-llm" python=3.11 pip
.venv-llm/bin/python -m pip --isolated install --require-hashes --only-binary=:all: --cache-dir .cache/pip-llm -r requirements/llm-gpu-cu126.lock
.venv-llm/bin/python -m pip check
.venv-gpu/bin/python scripts/prepare_llm.py
```

If using an existing approved Python 3.11 instead of Miniforge, create the LLM
environment with `python3.11 -m venv --copies .venv-llm`. Ordinary Linux venvs
often symlink the interpreter outside the repository; the application's path
policy rejects that. Use a prefix-local Conda interpreter or `--copies`.
Do not replace an existing environment while it is running a job.

The supplied GPU lock targets Linux x86_64, glibc >= 2.28, Python 3.11. Keep the
existing OCR `.venv-gpu` and local OCR models. Download models during the approved
setup stage; the PBS job runs offline and must not download on demand.

Submit the synthetic image test from the repository root:

```bash
qsub scripts/cetus_llm.pbs
qstat -u "$USER"
```

Or, to run only Qwen on OCR artifacts already on Cetus:

```bash
qsub -v OCR_RUN=outputs/your_previous_run scripts/cetus_llm.pbs
```

The script requests one GPU, four CPUs and 32 GB host RAM in `small_gpuq`. Its
two-hour walltime starts when the job runs, not while it is queued. It respects
the GPUs exposed by PBS. Queue availability and allocation policy remain
controlled by UTS. No long-running OCR/LLM inference belongs on the login node.

PBS writes a combined log named `invoice_qwen.o<job-number>` by default. It may
not appear until the job finishes. Inspect it and the new `outputs/qwen_.../`
directory; the script uses a unique run ID. First it checks the GPU and model
hashes, then runs real OCR/Qwen. A GPU preflight pass alone is not extraction
acceptance. We have not submitted this new Qwen job to Cetus from this task.

## Configuration and API

Environment variables apply to the terminal and child processes, not all future
terminals. `.env.example` is a template only; the app does not automatically
load a `.env` file. CLI `--extractor` overrides `INVOICE_EXTRACTOR` for that run.

| Variable | Default | Meaning |
| --- | --- | --- |
| `INVOICE_EXTRACTOR` | `rules` | `rules` or `llm`; also selects the API strategy |
| `LLM_DEVICE` | `PADDLEOCR_DEVICE`, otherwise `cpu` | Explicit `cpu` or `gpu:N`; no fallback |
| `LLM_PYTHON` | `.venv-llm/Scripts/python.exe` or `.venv-llm/bin/python` | Repo-relative worker interpreter, forward slashes |
| `LLM_DTYPE` | `auto` | CPU float32 / GPU float16; explicit float32/float16/bfloat16 |
| `LLM_TIMEOUT_SECONDS` | `1800` | Worker budget including imports, checksums, load and generation; max 14400 |
| `LLM_CPU_THREADS` | `4` | Torch CPU thread count, including GPU host work |
| `LLM_MAX_INPUT_TOKENS` | `8192` | Includes instructions and OCR; max 16384 |
| `LLM_MAX_NEW_TOKENS` | `2048` | Generated response cap; max 4096 |

Long input is rejected without truncation. Output that reaches its cap without
the end token is rejected. Increasing limits consumes additional memory/time;
the model's advertised context is not this application's configured limit.

During generation the worker updates token counts and elapsed time about every
ten seconds when new tokens arrive. For example, to inspect progress without
printing the document or model text, use a second PowerShell terminal:

```powershell
Get-Content outputs/your_qwen_run/llm_response.json -Raw | ConvertFrom-Json | Select-Object status, stage, input_tokens, output_tokens, generation_seconds
```

Zero output tokens can mean the model is still processing the prompt. These
updates are diagnostic counters; they are not proof of a valid extraction.

For the existing localhost API on Windows:

```powershell
$env:INVOICE_EXTRACTOR="llm"
$env:LLM_DEVICE="cpu"
$env:LLM_DTYPE="bfloat16"
.\.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

The request remains `POST /v1/invoices/process` with
`{"source":"private_inputs/my_receipt.png"}`. `/health` reports the selected
strategy; it does not load models or certify inference readiness. Configure
the process before starting the API. The original Docker images do not install
the new LLM environment; these instructions cover native Windows and PBS Linux.

## 輸出、驗證與人工確認

每次 LLM 執行會保存 `llm_request.json`（提示與設定）、`llm_response.json`
（模型原始回覆、版本、token 數、時間與執行狀態）。通過基本驗證後，另輸出
`extracted.json` 與 `review.json`。這些私有文件 artifacts 均由 Git 忽略，並排除於
Docker build context；manifest 記錄相應雜湊。請勿把真實收據的完整 artifacts 貼入共用 logs。

Qwen 負責輸出 15 個欄位及來源引文。`extracted.json` 維持 `tirbic-15-v2` 的 15 欄格式，
金額使用 Decimal-aware JSON number；未知欄位使用 `null`，`buyer_identity` 延用空字串。
Python 仍依 `total_cost` 計算既有的 `>=1000` 旗標，不計算補入缺少的總額或 GST。

基本驗證與來源確認分開處理：

| 檢查 | 行為 |
| --- | --- |
| 非法 JSON、欄位缺漏／多餘、型別不符、非法日期或 enum、NaN／Infinity、非 AUD | 執行失敗，不產生看似成功的 `extracted.json` |
| 缺少來源證據、引文找不到、引用內容無法支持欄位值 | 保留格式合法的欄位值，在 `review.json` 列出中文確認事項 |
| 引文僅有空白或換行差異 | 折疊為單一空格後比對；保留分隔，不把原本分離的數字接起來 |
| 模型輸出 `null` 或未知 buyer 空字串 | 保留缺值並記錄缺值欄位，不用舊規則或另一個模型猜補 |

例如，模型將商品分類為 `food`，卻引用文件中不存在的 `food` 作為原文時，分類值可以
保留，但會標記來源有疑問，讓人檢查奶茶等實際商品文字是否支持此分類。引文通過也
不能證明語意配對正確：模型仍可能把銀行當店家、把付款日當開立日。

`review.json` 包含 `requires_review`、`semantic_accuracy_verified: false`、固定 15 欄的
`fields`、中文 `issues` 及 `missing_fields`。缺值不一定代表辨識錯誤，例如收據原本
就可能沒有到期日；應與人工標註或原圖一起確認。不要把 `requires_review: false`
視為準確率證明。

| `manifest.status` | 意義 |
| --- | --- |
| `completed_needs_review` | 已產生符合基本格式的結果，但有欄位需要人工確認 |
| `completed` | 已完成處理，沒有自動檢查發現的確認事項；仍未驗證內容準確率 |
| `failed` | 執行或基本驗證失敗；保留已取得的 OCR／模型 artifacts 供排查 |

CLI 與 API 同時回傳 `status`、`requires_review`、review 摘要及 artifact 路徑。
API 摘要包含 `issue_count`、`fields_requiring_review`、`semantic_accuracy_verified`。
CLI 以中文提示待確認欄位與 review 檔案位置；`completed_needs_review` 的退出碼仍為 0，
表示已完成處理，執行或基本驗證失敗則為 1。自動化流程須檢查狀態，不可只看退出碼。
看到 `completed_needs_review` 時，應先讀 `review.json`，再決定哪些值可以採用。
`extracted.json` 存在僅表示基本契約有效，不代表所有值已經人工確認。
現有 `rag prepare` 仍只接受 `completed`，不接受 `completed_needs_review`；本次不擴充
RAGFlow 流程，私有收據也仍禁止送往 RAGFlow。

失敗時請在本機檢查 manifest 與回覆的 `stage`、`error_type`、`execution`、`validation`。
終端機及 API 錯誤訊息維持遮蔽文件內容。修正環境、輸入或提示後，以新的 run ID 重跑；
不覆寫舊結果，不自動 retry、不自動修補 JSON，也不切回 rules 模式。
請使用已審核的同一份 ground truth 評估各欄，才可判斷是否比 rules 更準確。

## Tests and source references

To compare rules and Qwen, use the same verified OCR run for both and evaluate
each `extracted.json` against the same reviewed current-schema reference:

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_fields.py --expected private_inputs/reviewed-fields.json --predicted outputs/your_qwen_run/extracted.json --run-id evaluate_qwen_01
.\.venv\Scripts\python.exe scripts/evaluate_fields.py --expected private_inputs/reviewed-fields.json --predicted outputs/your_rules_run/extracted.json --run-id evaluate_rules_01
```

Substitute existing paths and unique run IDs. This evaluator is offline and does
not run OCR or Qwen. Legacy `nature_of_expense` annotations need review for the
new fields and percentage units first. See [evaluation rules](EVALUATION.md).

For future changes, the relevant files are:

```text
app/llm/contract.py               field instructions, basic validation and field review
app/llm/adapter.py                isolated worker invocation and failure artifacts
app/llm/worker.py                 offline Transformers model loading and generation
app/llm/runtime.py                explicit device, dtype and package checks
app/llm/models.py                 explicit preparation and model integrity checks
app/schemas/invoice.py            the shared 15-field types/enums
app/pipeline.py                   OCR, extraction and replay orchestration
requirements/llm-*.lock           separate CPU/GPU dependency hashes
requirements/llm-model.lock.json  shared model revision and file hashes
scripts/cetus_llm.pbs             the GPU job submitted by the user
```

When editing field instructions, update `PROMPT_VERSION` and add synthetic
contract/regression cases. Replay OCR for comparison; neither model downloading
nor fine-tuning is needed for a prompt-only change. Change the shared schema
only when the agreed field definitions change.

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not integration" -q
$env:RUN_LLM_INTEGRATION="1"
$env:LLM_DEVICE="cpu"
$env:LLM_DTYPE="bfloat16"
.\.venv\Scripts\python.exe -m pytest -m llm_integration -v
```

The opt-in LLM integration test uses real Qwen and handwritten **synthetic OCR
text**, not a photograph. It retains diagnostics under `.runtime/llm-integration-*`.
It does not establish full image-to-JSON accuracy. Unit tests use explicit fake
workers/models. See [validation records](../VALIDATION.md) for actual results.

Primary sources: [Qwen model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507),
[PyTorch 2.8 installation recipes](https://pytorch.org/get-started/previous-versions/),
[uv index resolution](https://docs.astral.sh/uv/pip/compatibility/#packages-that-exist-on-multiple-indexes).
The two `.in` recipes generate separate platform locks with hashes. Resolution
uses `--index-strategy unsafe-best-match` only across public PyPI and the official
PyTorch index, with the exact Torch build pinned, so ordinary dependencies are
not restricted to older copies on the Torch index. Never add an untrusted index.
Full regeneration commands are recorded at the top of each lock file.
