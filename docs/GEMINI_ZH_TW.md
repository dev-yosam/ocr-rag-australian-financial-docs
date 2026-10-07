# Gemini 3.5 Flash-Lite：從既有 OCR 抽取 15 欄

本功能重用已保存的 `raw.json`，不重新執行 OCR，不需要 GPU、Qwen 權重或
`.venv-llm`。目前只支援 PaddleOCR-VL 的 `res.parsing_res_list` 格式，尚未加入
PP-Structure adapter。`parse`、rules、Qwen 及 FastAPI 的原有行為不變。

```text
已完成的 PP-DocLayoutV3 + PaddleOCR-VL run
  → 檢查 manifest / raw.json / parsed.md 雜湊
  → ocr_blocks.json：保留每頁全部 parsing blocks、順序、類型、座標、內容
  → Gemini 3.5 Flash-Lite（Google HTTPS API，文字輸入）
  → llm_response.json：原始 API 回答
  → validation.json + review.json：格式檢查／人工確認事項
  → extracted.json：格式合法的 15 欄，保留 Gemini 值
```

Python 不使用 matching rules 補值，也不覆寫 Gemini 的金額、日期、分類或 >=1000
布林值。例如模型給 `total_cost=1100`、threshold=false，會保留 false，另列不一致。
這不同於既有 Qwen 契約的 threshold 計算。所有模式共用 15 欄名稱與基本型別。

## 1. 環境

現有 `.venv` 已有需要的 `httpx==0.28.1`、Pydantic、simplejson，無需額外 SDK。
全新環境只需 Python >=3.11 和 `requirements/app.lock`，不用 OCR/LLM lock。
以下指令在 **Windows PowerShell** 的專案根目錄執行，可整段貼上，不包含提示字。

```powershell
Set-Location "C:\Users\sam84\Documents\Codex\2026-09-11\new-chat\ocr-rag-australian-financial-docs"
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m app.cli extract --help
```

## 2. 先離線查看將送出的資料

以下使用你已下載的 Cetus OCR 目錄；目錄存在且雜湊吻合才會成功。

```powershell
$sourceRun = "outputs/cetus_ti-photo-241_gpu_ocr_112612_hpc-head01"
$previewRun = "ti-photo-241_gemini_preview_" + (Get-Date -Format "yyyyMMdd_HHmmss")
.\.venv\Scripts\python.exe -m app.cli extract $sourceRun --extractor gemini --dry-run --run-id $previewRun
```

查看 `outputs/<previewRun>/ocr_blocks.json` 與 `llm_request.json`。
這一步 `status=prepared`、`network_attempted=false`，不需要 key、沒有雲端費用，
也不會有 `llm_response.json` 或 `extracted.json`。它不是辨識成功證據。
實際送出時仍以原始 `$sourceRun` 為輸入，建立新的 run；不是送出 preview 目錄。

與直接餵 `parsed.md` 的差異：Paddle 的 Markdown 可能排除頁首／頁尾，
但這裡保留所有 parsing blocks。文字、HTML 表格及區塊數值不做 matching 或重排。
每塊新增 `p1:b0` 形式的唯一引用，代表第 1 頁、原始清單第 0 塊；保留原
`block_id`、`block_order` 等欄位。未傳送 layout detector 的整份 metadata 或圖像。
不能因此補回 OCR 原本就漏讀的內容。

## 3. 設定自己的 key

在 [Google AI Studio](https://aistudio.google.com/api-keys) 建立 Gemini API key，
確認自己的專案可用此模型。不要把 key 貼進聊天、程式、Git 或 PBS 腳本。
Google 的 [資料使用／付費條款](https://ai.google.dev/gemini-api/terms) 與
[價格](https://ai.google.dev/gemini-api/docs/pricing) 依所用服務方案而異，實際送出前
確認資料適用的方案。這個功能會將收據的 **OCR 文字與座標傳至 Google**，
不再是完全離線處理，但不會上傳圖片或 PDF。

PowerShell 使用隱藏輸入，不在命令歷史留下 key 字面值：

```powershell
$geminiSecret = Read-Host "Gemini API key" -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new("", $geminiSecret).Password
Remove-Variable geminiSecret
$env:GEMINI_TIMEOUT_SECONDS = "120"
$env:GEMINI_MAX_OUTPUT_TOKENS = "8192"
```

只作用於目前終端及其子程序。`.env.example` 只是名稱清單，程式**不自動載入 `.env`**。
不要用 `echo`、`Get-ChildItem Env:` 等方式展示 key。

| 設定 | 預設／限制 |
| --- | --- |
| `GEMINI_MODEL` | 預設 `gemini-3.5-flash-lite`；另允許明確選擇 `gemini-flash-lite-latest`，不自動替換 |
| `GEMINI_API_KEY` | 真實呼叫必填；preview 不讀取 |
| `GEMINI_TIMEOUT_SECONDS` | 120 秒，允許 1..600；網路等待上限，不保證此時間內成功 |
| `GEMINI_MAX_OUTPUT_TOKENS` | 8192，允許 512..16384；包含模型輸出的 token 預算，影響成本／截斷 |
| OCR 輸入限制 | 組合後 200,000 字元；超過直接拒絕，不默默截斷 |
| 自動重試 | 無；429、逾時及其他失敗需自行檢查後新開 run |

## 4. 明確送出一次

若要測試原本使用的 Flash-Lite latest alias，在相同終端先設定：

```powershell
$env:GEMINI_MODEL = "gemini-flash-lite-latest"
```

不需要重新申請 key。想切回原模型，設為 `gemini-3.5-flash-lite`。
`latest` 是會更新指向的 alias，不保證與舊專案當時的模型相同。
manifest 的 `model` 保存你指定的名稱，`generation.model_version` 保存 provider
回傳的版本（如果有提供且格式合法）；完整回應仍在 llm_response.json。
這只是明確切換模型，不能保證解決 HTTP 400，也不會失敗後自行嘗試其他模型。

此指令會送資料至 Google，可能產生 API 費用。一次處理一份既有 OCR run。

```powershell
$geminiRun = "ti-photo-241_gemini_" + (Get-Date -Format "yyyyMMdd_HHmmss")
.\.venv\Scripts\python.exe -m app.cli extract $sourceRun --extractor gemini --run-id $geminiRun
Invoke-Item -LiteralPath (Join-Path "outputs" $geminiRun)
```

想換文件，只需修改 `$sourceRun` 和輸出 run 名稱。來源原圖若仍在本機會一併核對
source hash；若只有下載的 OCR artifacts，仍可重用，但原圖 hash 僅從原 manifest
繼承，不宣稱已重新驗證原圖。雜湊核對用來防止意外改動，不是數位簽章。

測試結束可清除本終端的 key：

```powershell
Remove-Item Env:GEMINI_API_KEY
```

## 5. 結果在哪裡

若 API 一直 HTTP 400，先停止重送收據，在已有 key 的同一終端執行：

```powershell
.\.venv\Scripts\python.exe scripts/check_gemini_environment.py
```

這只呼叫一次官方 `models.get`：沒有 request body、不讀取收據、不送 prompt/schema、
不請模型生成內容、不重試。輸出只含模型名稱、key 是否存在／是否含空白等布林值、
HTTP 狀態和安全分類，不印 key 或原始回覆。`ok=true` 只代表模型 metadata 可取得，
不證明 generateContent 額度／schema／推論已成功。若仍 HTTP 400，可依 body_format
區分 JSON、HTML、空回覆與其他內容，不能單憑 HTML 斷定是網路代理或 key 問題。
這個指令依 [官方 models.get](https://ai.google.dev/api/models#method:-models.get) 實作。

每次建立 `outputs/<run_id>/`，不覆寫原來 CPU／Cetus 的結果。

| 檔案 | 用途 |
| --- | --- |
| `raw.json`、`parsed.md` | 原 OCR artifacts 的逐位元組副本；parsed.md 不作為 Gemini 輸入 |
| `ocr_blocks.json` | 從 raw 選出的全部 parsing blocks，含頁碼與唯一 block_ref |
| `llm_request.json` | 實際 REST request body：system prompt、OCR 區塊、輸出 schema；不含 key |
| `llm_response.json` | HTTP 200 的原始回答，含候選文字、usageMetadata、modelVersion（provider 有提供時）；不是直接的 15 欄 JSON |
| `validation.json` | 15 欄、型別、合法日期、enum、有限 Decimal、ABN 格式等檢查；不評分準確率 |
| `review.json` | 缺值、無 evidence、引文不在引用區塊、threshold 不一致；不回填或改值 |
| `extracted.json` | 基本驗證通過才產生；所有 15 欄、數值為 JSON number，buyer_identity 缺值為空字串，其餘未知值為 null |
| `manifest.json` | 原來源／OCR provenance、模型、prompt 版本、設定、雜湊、狀態與耗時 |

`completed_needs_review` 表示格式通過但有上述待確認事項。`completed` 也不等於
語意正確，`semantic_accuracy_verified` 一律 false。目前證據檢查只確認引用的
區塊存在且含有引文，不證明該引文支持欄位值或角色；分類／日期／金額仍需人工
ground truth 比對。`currency` 是 API 回答 envelope 的 metadata，非第 16 個欄位；
明確非 AUD 回答不輸出成功 invoice。未指定 currency 不代表已證實為 AUD。

HTTP 非 200 只保存遮蔽後的狀態／錯誤碼，不保存可能回顯 key 的錯誤 body。
會在記憶體中檢查有大小上限的錯誤 body，保存已知的 Google status／reason、
已知請求欄位名稱與固定中文提示；不保存原始 message、project、metadata 或引文。
例如 `invalid_api_key`、`api_not_enabled`、`invalid_request_schema`。`KEY_PRESENT`
只代表本機變數非空，不證明 Google 接受 key。無法分類時仍保留 HTTP 錯誤碼，
不猜測原因、不自動換模型或重送。舊失敗 run 不會被改寫，需新一次明確呼叫才會取得診斷。
HTTP 200 但 JSON 壞掉／安全封鎖／MAX_TOKENS 截斷時，仍保存取得的 body，
`status=failed`，沒有 extracted.json。回覆過大或含 key 回顯時例外不保存 body。
`network_attempted=true` 只代表嘗試送出，不保證 Google 有處理；逾時仍可能已計費。

## 6. Cetus

最簡单的方式：把 Cetus 已完成的 OCR artifacts 下載回筆電後，在本機呼叫 Gemini。
這個階段不需要再排 GPU。Windows CPU 與 Cetus GPU 的 OCR 結果都用相同命令。

若要在 Cetus 發 API request，需先確認學校對外網路／工作政策；本次未驗證。
在允許的 shell／工作環境中，已有 `.venv-gpu` 可以執行相同 extract 指令：

```bash
cd /shared/homes/u175668/ocr-rag-australian-financial-docs
read -r -s -p 'Gemini API key: ' GEMINI_API_KEY
export GEMINI_API_KEY
printf '\n'
export GEMINI_TIMEOUT_SECONDS=120
.venv-gpu/bin/python -m app.cli extract outputs/YOUR_OCR_RUN --extractor gemini --run-id "gemini_$(date +%Y%m%d_%H%M%S)"
unset GEMINI_API_KEY
```

`YOUR_OCR_RUN` 必須換成實際目錄。不要透過 `qsub -v GEMINI_API_KEY=...` 或 `qsub -V`
傳 key，避免 scheduler metadata 暴露。無需改動 CUDA、Paddle 或下載 Gemini 權重。

## 7. 開發檔案與驗證範圍

- `app/gemini/contract.py`：prompt、15 欄 response schema、OCR block 選取與非修改式驗證。
- `app/gemini/client.py`：固定 Google HTTPS endpoint，單次請求、原回答、錯誤遮蔽。
- `app/gemini/pipeline.py`：已存 OCR 雜湊檢查、新 run、狀態及 artifacts。
- `app/gemini/config.py`：兩個允許的模型名稱和 Gemini 專屬設定，不讀 Qwen/Paddle 設定。
- `app/cli.py`：`extract --extractor gemini [--dry-run]`。目前未擴充 FastAPI cloud endpoint。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_gemini.py -q
.\.venv\Scripts\python.exe -m pytest -m "not integration" -q
```

測試用合成資料與 `httpx.MockTransport`，不代表 Gemini live API 已通過，
更不代表十張收據的準確率。實際結果及限制另記於 `VALIDATION.md`。

官方依據（2026-10-07 核對）：
[模型與能力](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)、
[GenerateContent REST](https://ai.google.dev/api/generate-content)、
[Structured output](https://ai.google.dev/gemini-api/docs/structured-output)。
使用 `responseMimeType=application/json` 與 `responseJsonSchema`；結構化輸出不保證內容正確。
