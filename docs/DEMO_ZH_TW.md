# Windows 本機示範操作指南

若要使用 **GPT 雲端 API** 重用現有 CPU／Cetus OCR 結果，請看
[GPT 中文操作指南](OPENAI_ZH_TW.md)。`--extractor openai` 會直接呼叫 OpenAI，
不需 dry run，也不需本機 GPU 或 Qwen 環境。

若要使用 **Gemini 3.5 Flash-Lite** 重用現有 CPU／Cetus OCR 結果，請看
[Gemini 中文操作指南](GEMINI_ZH_TW.md)。該模式需明確選用與 API key，
會送出 OCR 文字／座標至 Google；以下純 OCR／Qwen 步驟仍在本機執行。

純 OCR 適用於已準備好 `.venv` 與 OCR 模型的 Windows 筆電；只有後面的 Qwen
完整流程需要額外的 `.venv-llm` 與 Qwen 模型。
所有程式指令都在專案根目錄的 **PowerShell** 執行。每一行都是獨立指令；不要複製
終端顯示的 `PS C:\...>` 或 `>>` 提示字。

目前 CPU 的完整 Qwen 推論可能非常慢，並耗用大量記憶體。正式示範建議先準備結果，
現場依序展示圖片、OCR、欄位與待確認事項。若現場重新跑模型，須清楚區分已完成和
仍在運算的部分；不能保證短時間完成。這份指南不會自動執行模型或下載套件。

## 0. 只看 OCR，不執行 Qwen 或 Python rules

使用 `parse` 指令，不使用 `process --extractor rules`。每次只指定一份 PNG、JPG、
JPEG 或 PDF；多頁 PDF 仍是一份文件。這一步不處理整個資料夾，也沒有批次指令。

```powershell
Set-Location "C:\Users\sam84\Documents\Codex\2026-09-11\new-chat\ocr-rag-australian-financial-docs"
$env:PADDLEOCR_DEVICE = "cpu"
$env:PADDLEOCR_TIMEOUT_SECONDS = "3600"
$env:OMP_NUM_THREADS = "1"
$env:PYTHONIOENCODING = "utf-8"
$ocrRun = "ocr_" + (Get-Date -Format "yyyyMMdd_HHmmss")
.\.venv\Scripts\python.exe -m app.cli parse "samples/tax_invoices/sample_invoice.png" --run-id $ocrRun
```

最後一行使用專案內的合成樣本；要換成自己的文件，將來源改為
`private_inputs/ocr_batch10/<你的檔名>`。`3600` 是 OCR 子程序等待上限，
不是保證一小時內成功。原圖不會修改；每次重跑都重新產生 `$ocrRun`。

只需要 Paddle 的執行環境及本機 OCR 模型。`parse` 忽略 `INVOICE_EXTRACTOR`、
`LLM_*` 和 RAGFlow 環境變數；不檢查 Qwen 模型，不啟動抽取器。
文件處理不下載模型、不連線外部服務。需要準備 OCR 模型時，另外明確執行
`scripts/prepare_models.py`，不可把模型準備當成 OCR 已成功。

正常完成後，在同一個終端開啟本次目錄：

```powershell
Invoke-Item -LiteralPath (Join-Path "outputs" $ocrRun)
```

成功的目錄只有三個主要檔案：

| 檔案 | 用途 |
| --- | --- |
| `raw.json` | Provider 原始逐頁 JSON，含版面與辨識結果；不回寫欄位值。 |
| `parsed.md` | 正規化換行與非語意空白後的 Markdown，保留 HTML 表格、內部空白與頁面邊界。 |
| `manifest.json` | `schema_version=ocr-run-v1`、來源與結果雜湊、版本、裝置、耗時及 OCR 狀態。 |

manifest 的 `mode=ocr_only`、`status=completed`、`ocr_status=completed` 表示解析
流程正常完成；`extraction.strategy=none`、`extraction.status=not_requested` 明確
表示沒有要求欄位抽取。`semantic_accuracy_verified=false`，不宣稱文字或表格正確。
沒有 `extracted.json`、`review.json`、`llm_request.json` 或 `llm_response.json` 是正常的。
`elapsed_seconds` 包含 parser 初始化、OCR 與結果處理，不是單純模型推論時間。

失敗時 `status` 與 `ocr_status` 都是 `failed`，已取得的逐頁 raw 會保留；
若連原始頁面結果都還沒取得，目錄可能只有 manifest。空結果或頁數不一致不會
標示完成。路徑／格式等前置檢查失敗時，可能尚未建立 output 目錄。

之後仍可用 `python -m app.cli extract outputs/<run_id> --extractor llm` 在新目錄
重新抽取欄位；只有執行這個後續命令時才需要 LLM 環境。不要修改已保存的 OCR 檔案，
否則重用時的雜湊檢查會拒絕它。

Cetus 在 PBS 分配的 GPU 工作內，用 `.venv-gpu/bin/python` 執行同一個 `parse`
指令，並設定 `PADDLEOCR_DEVICE=gpu:0`。不要直接套用 `scripts/cetus_llm.pbs`，
該腳本會啟動 Qwen。這次尚未提供純 OCR PBS 腳本或十份文件的批次功能。

以下第 1 至 9 節保留完整 OCR＋Qwen 的示範方式，與本節的純 OCR 模式不同。

## 1. 開啟專案與終端

IDE 不是執行的必要條件。你可以使用 PowerShell，或在已安裝的 VS Code／Cursor 中
開啟專案資料夾，再開啟內建 Terminal，選擇 PowerShell。

專案根目錄：

```text
C:\Users\sam84\Documents\Codex\2026-09-11\new-chat\ocr-rag-australian-financial-docs
```

先切到正確位置：

```powershell
Set-Location "C:\Users\sam84\Documents\Codex\2026-09-11\new-chat\ocr-rag-australian-financial-docs"
Get-Location
Test-Path .\app\cli.py
Test-Path .\.venv\Scripts\python.exe
Test-Path .\.venv-llm\Scripts\python.exe
```

三個 `Test-Path` 應該都是 `True`。若不是，先確認所在資料夾，或查看安裝文件
[LLM.md](LLM.md)，不要在 demo 當下直接重建既有環境。

示範說明：「這裡是主程式的資料夾；IDE 用來查看圖片、程式和結果，終端負責執行。」

## 2. 放入圖片

| 資料夾 | 用途 |
| --- | --- |
| `private_inputs/` | 放本機測試圖片；PNG、JPG、JPEG 或 PDF。程式只處理指令指定的那一份。 |
| `samples/tax_invoices/` | 專案附的合成發票，可作為示範素材。 |
| `outputs/<run_id>/` | 程式自動產生的每次執行結果；每次使用新目錄。 |
| `.models/` | 已下載的模型，正常執行不需重新下載。 |
| `.venv/` | 主程式與 PaddleOCR 的 Python 環境。 |
| `.venv-llm/` | Qwen 的獨立 Python 環境，由主程式自動呼叫。 |

新圖片可在檔案總管中複製到 `private_inputs/`。不要把資料放進 `.venv` 或 `.models`。
真實圖片及 runtime 結果維持 Git 忽略；示範時只選擇可對觀眾展示的資料。

本機已有這張測試圖，以下以它示範：

```powershell
$demoSource = "private_inputs/2026-09-16 000525.png"
Test-Path -LiteralPath $demoSource
```

要換成合成圖片，將 `$demoSource` 改成下面這行即可：

```powershell
$demoSource = "samples/tax_invoices/sample_invoice.png"
```

每次選一個來源；不需要清空其他圖片。CLI 的來源路徑使用相對於 repository 的正斜線
路徑，有空格的檔名也要放在引號內。單檔上限 20 MiB；圖片上限 2500 萬像素。

## 3. 設定本機 CPU 模式

在同一個 PowerShell 終端依序執行：

```powershell
$env:PADDLEOCR_DEVICE = "cpu"
$env:PADDLEOCR_TIMEOUT_SECONDS = "3600"
$env:OMP_NUM_THREADS = "1"
$env:LLM_DEVICE = "cpu"
$env:LLM_DTYPE = "bfloat16"
$env:LLM_CPU_THREADS = "4"
$env:LLM_TIMEOUT_SECONDS = "3600"
$env:LLM_PYTHON = ".venv-llm/Scripts/python.exe"
$env:PYTHONIOENCODING = "utf-8"
```

- 沒有顯示文字是正常的；這些指令只設定環境變數。
- OCR 與 Qwen 都明確使用 CPU。`bfloat16` 是此筆電先前使用的精度設定，不代表所有
  CPU 上都會很快，也不保證記憶體足夠。
- 兩個 `3600` 分別是 OCR／Qwen 子程序的等待上限，不是「保證一小時內成功」。
  休眠或暫停會影響實際經過時間和計時的解讀。
- 設定只影響這個終端及它啟動的子程序；新開終端須重新設定。程式不會自動讀取 `.env`。
- 以下都使用明確的 Python 路徑，**不需要 Activate.ps1，也不需要輪流啟用兩個環境**。
  請用 `.venv` 執行主程式，讓它自動在 `.venv-llm` 啟動 Qwen。

示範前可以檢查環境，這兩行不是正式圖片辨識：

```powershell
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv-llm\Scripts\python.exe scripts/check_llm_environment.py --models
```

前者檢查 Paddle CPU 計算與 OCR import；後者檢查 Qwen 執行環境與模型雜湊。
檢查通過不等於圖片或欄位抽取已成功。

## 4. 重新跑完整流程

先用日期時間建立新的 run ID，再執行：

```powershell
$demoRun = "demo_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$demoOutput = Join-Path "outputs" $demoRun
Write-Output $demoRun
.\.venv\Scripts\python.exe -m app.cli process $demoSource --extractor llm --run-id $demoRun
```

程式實際做的事：

```text
指定的圖片
    ↓ PP-DocLayoutV3：找出版面區塊
    ↓ PaddleOCR-VL-1.6：辨識內容與表格
raw.json ＋ parsed.md
    ↓ Qwen3-4B：讀取 OCR Markdown，依 15 欄定義配對
    ↓ Python：基本格式驗證＋逐欄來源檢查
extracted.json ＋ review.json
```

Qwen 在此模式讀 OCR Markdown，不直接看原圖。它不使用舊 matching 規則補值。
Python 仍依總額計算既有 `>=1000` 旗標；其他缺值不猜補。

示範說明：「前段把圖片變成可讀文字和表格；後段理解文字並填入欄位。
程式檢查輸出格式，有疑問的來源會標記人工確認，不只因引文問題就丟棄整張結果。」

`--extractor llm` 很重要。省略時依環境設定選擇，預設是 `rules`。
`--extractor rules` 是完整 OCR 加上舊規則抽取，不是 Qwen，也不是純 OCR 指令。
只需要 OCR 時改用本指南第 0 節的 `parse` 子命令。

每次重跑都重新產生 `$demoRun`。沿用既有 run ID 會報錯，不會覆寫舊結果。
正常執行時終端可能長時間沒有輸出；worker 不會把收據內容或半成品答案列印到 logs。
需要停止時，在執行主程式的終端按一次 **Ctrl+C**，等待回到提示字。

## 5. 執行中看進度

可以在 IDE 左側展開 `outputs/`，找到剛剛的 run ID。先出現 `manifest.json` 是正常的；
OCR 完成後才會出現 `raw.json`、`parsed.md`，Qwen 開始後才有 `llm_response.json`。

若開第二個 PowerShell 看進度，它不會繼承第一個終端的 `$demoRun`。先切到專案根目錄，
並把下面的示例名稱換成第一個終端印出的實際 run ID：

```powershell
Set-Location "C:\Users\sam84\Documents\Codex\2026-09-11\new-chat\ocr-rag-australian-financial-docs"
$demoWatchRun = "demo_YYYYMMDD_HHMMSS"
$demoWatchOutput = Join-Path "outputs" $demoWatchRun
Get-Content -LiteralPath (Join-Path $demoWatchOutput "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json | Select-Object status
```

等 `llm_response.json` 出現後，才執行這行：

```powershell
Get-Content -LiteralPath (Join-Path $demoWatchOutput "llm_response.json") -Raw -Encoding UTF8 | ConvertFrom-Json | Select-Object status, stage, input_tokens, output_tokens, generation_seconds
```

`stage=generating` 代表進入生成階段，`output_tokens=0` 可能仍在處理輸入。
計數只在新 token 到來時更新，不是完整的進度百分比；沒有變化不等於已成功或一定卡死。
worker 的 `status` 此時可能仍顯示 `initializing`；整次流程是否完成，請以
`manifest.json` 的 `status` 為準。

## 6. 完成後看哪裡

回到第一個終端，可以打開本次結果資料夾：

```powershell
Invoke-Item -LiteralPath $demoOutput
```

或直接在 IDE 的檔案樹中打開它：

```text
outputs/<本次 run ID>/
├─ manifest.json       執行狀態、來源／檔案雜湊、待確認摘要
├─ raw.json            原始 OCR 結果與版面資訊
├─ parsed.md           可閱讀的 OCR 文字與表格
├─ llm_request.json    實際送給本機 Qwen 的提示與設定
├─ llm_response.json   模型回應、階段、執行資訊
├─ extracted.json      格式合法的 15 欄結果
└─ review.json         中文逐欄確認事項與缺值清單
```

`extracted.json` 與 `review.json` 只有在模型生成完成且基本驗證通過後才會出現。
生成中、逾時、被停止或基本格式失敗時，可能沒有這兩份檔案。
`test_report.md` 是助手另行整理的報告；目前 CLI 不會每次自動生成這份完整報告。

| 狀態 | 示範時如何解釋 |
| --- | --- |
| `processing` | 還在執行，不能當成結果。 |
| `completed` | 已完成自動檢查；不代表所有語意和內容都正確。 |
| `completed_needs_review` | 已輸出合法格式的欄位，但有內容需要人工確認。 |
| `failed` | 本次流程未完成；查看保留下來的 OCR、模型回應或失敗資訊。 |

CLI 的 `completed_needs_review` 仍回傳退出碼 0，因為有可檢查的輸出；不能只看退出碼
就把所有欄位當成正確。`null` 可能是原圖沒有該資料、日期有歧義，或模型漏填。

## 7. 只重跑 Qwen，省去 OCR

現有這次圖片的 OCR 已成功保留，即使 manifest 是 `failed`，仍可重用已保存且可核對
雜湊的 `raw.json`、`parsed.md` 和來源版本資訊。依第 3 步設定同一個終端後執行：

```powershell
$demoRun = "demo_llm_" + (Get-Date -Format "yyyyMMdd_HHmmss")
$demoOutput = Join-Path "outputs" $demoRun
.\.venv\Scripts\python.exe -m app.cli extract "outputs/cpu_llm_20260916_000525_20260926_01" --extractor llm --run-id $demoRun
```

這會重新啟動 Qwen，也可能耗時很久；不是立即讀取舊模型答案。原 OCR 目錄不會被覆寫。
不要手動修改舊 `raw.json`／`parsed.md`，否則雜湊核對會拒絕重用。

## 8. 現場展示既有結果

短時間的現場說明可以依序展示同一張圖片的四份資料：

1. `private_inputs/b-photo-1.jpg`：原始圖片。
2. `outputs/llm_review_recheck_20260926T015438Z/parsed.md`：先前的真實 OCR 文字。
3. 同資料夾的 `extracted.json`：歷史 Qwen 回應經新版驗證後保留的欄位。
4. 同資料夾的 `review.json`／`test_report.md`：哪些欄位要確認、測試限制。

請明確說明：「這是先前保存的 Qwen 回應經新版驗證器重查，並非今天現場生成，也不是
新版提示詞重新推論的證明。」這個 `llm_review_recheck_...` 目錄只供展示，不能直接拿來
當 `app.cli extract` 的來源，因為它的手動重查 manifest 缺少該命令要求的版本資訊。
若要重跑 b-photo-1 的 Qwen，可使用原始 OCR 目錄 `outputs/cpu_b_photo_1_01`。

`2026-09-16 000525.png` 那次可展示
`outputs/cpu_llm_20260916_000525_20260926_01/parsed.md` 與 `test_report.md`；它只完成 OCR，
Qwen 因記憶體壓力被助手停止，沒有欄位 JSON，不能與另一張圖的 JSON 混為同次結果。

## 9. 解說程式時可以指出哪些檔案

| 檔案 | 用途 |
| --- | --- |
| `app/cli.py` | 接收終端指令與顯示狀態。 |
| `app/pipeline.py` | 串接 OCR、Qwen、驗證與檔案保存。 |
| `app/paddleocr/worker.py` | 執行完整 PaddleOCR-VL 解析。 |
| `app/llm/worker.py` | 在獨立環境載入並執行本機 Qwen。 |
| `app/llm/contract.py` | 15 欄提示、基本驗證、來源確認事項。 |
| `app/schemas/invoice.py` | 正式欄位名稱、型別及分類選項。 |

這套終端 demo 不需要啟動 Docker、RAGFlow 或網頁 API，也不需要 API key。
本指南只新增操作說明；沒有更動程式、啟動推論、安裝依賴或修改 Git。
