# GPT 欄位抽取：直接使用已保存的 OCR 結果

流程：PP-DocLayoutV3 → PaddleOCR-VL-1.6 → 已保存的 OCR 區塊 → OpenAI GPT →
15 欄 JSON 與人工確認事項。這次只執行最後的 API 抽取，不重新跑 OCR。

使用既有 `.venv` 的 httpx 0.28.1，不需另外安裝 OpenAI SDK、GPU 套件或 Qwen。
支援 Windows CPU 筆電與 Linux；API 推論在 OpenAI 執行。Cetus 外網政策未實測，
可將 Cetus OCR 結果下載到本機 `outputs/` 後直接測試。

## 1. 在本機 PowerShell 設定金鑰

請分兩段操作：先貼以下程式，按 Enter，再於詢問提示中貼完整 key。
不要把後面的執行指令一起貼進 key 輸入提示。

```powershell
cd "C:\Users\sam84\Documents\Codex\2026-09-11\new-chat\ocr-rag-australian-financial-docs"
$openaiSecret = Read-Host "貼上完整 OpenAI API key，按 Enter" -AsSecureString
```

完成 key 輸入後，整段貼以下程式，內容不用替換：

```powershell
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new("", $openaiSecret).Password
Remove-Variable openaiSecret
if ($env:OPENAI_API_KEY.Length -lt 20) { throw "API key 太短，請重新複製完整 key。" }
$env:OPENAI_MODEL = "gpt-6-luna"
$env:OPENAI_REASONING_EFFORT = "none"
$env:OPENAI_TIMEOUT_SECONDS = "180"
$env:PYTHONIOENCODING = "utf-8"
```

程式不會顯示 key，也不檢查其他帳戶／憑證。長度檢查只防止誤貼一個字，不能证明 key 有效。
環境變數只在目前 PowerShell 與子程序有效；開新視窗需重新設定。`.env` 不會自動載入，
不要以為填入 `.env` 就已生效。API 使用費與 ChatGPT 訂閱分開，模型存取權以帳號為準。

## 2. 直接執行一張（會連線、傳出 OCR 內容並可能計費）

```powershell
$gptRun = "ti-photo-241_gpt_" + (Get-Date -Format "yyyyMMdd_HHmmss")
.\.venv\Scripts\python.exe -m app.cli extract "outputs/cetus_ti-photo-241_gpu_ocr_112612_hpc-head01" --extractor openai --run-id $gptRun
```

不需要 `--dry-run`；該選項只屬於既有 Gemini 功能。`openai` 是 provider 名稱，
不是模型名稱。目前只有 `extract` 支援 OpenAI，`parse` 保持純 OCR。
未指定 run ID 時自動建立 `gpt_<uuid>`。同名 run 不覆寫，重跑請產生新 ID。

成功時開啟結果：

```powershell
Invoke-Item -LiteralPath (Join-Path "outputs" $gptRun)
Get-Content -Encoding UTF8 "outputs/$gptRun/extracted.json"
```

如需比較另一個模型，在同一終端執行：

```powershell
$env:OPENAI_MODEL = "gpt-5.4-mini"
$gptRun = "ti-photo-241_gpt54mini_" + (Get-Date -Format "yyyyMMdd_HHmmss")
.\.venv\Scripts\python.exe -m app.cli extract "outputs/cetus_ti-photo-241_gpu_ocr_112612_hpc-head01" --extractor openai --run-id $gptRun
```

不會自動切換模型或重試。允許明確 GPT 模型 ID；該模型必須支援 Responses API、
Structured Outputs 與指定 reasoning effort。名稱通過本機格式檢查不等於帳號可以使用。

Linux 可用 `read -s -p 'OpenAI API key: ' OPENAI_API_KEY`，完成後執行
`export OPENAI_API_KEY`、`export OPENAI_MODEL=gpt-6-luna`，再用適當 Python 環境執行
相同 `-m app.cli extract ... --extractor openai`。不要把 key 寫入 PBS 腳本或 Git。

## 3. 輸入與輸出

輸入從 `raw.json` 逐頁取出所有 `parsing_res_list` 區塊，包括 header/footer。
保留文字、HTML 表格、座標與順序，加入 `p1:b0` 等引用 ID。只傳允許的欄位；
圖片、PDF、來源檔案路徑、原始 provider 附加 metadata 不送出。
輸入超過 200,000 字元會報錯，不默默截斷。執行前驗證 manifest、raw、Markdown 的
來源雜湊；來源圖片仍存在時也驗證圖片雜湊。原 run 保持不變。

| 檔案 | 用途 |
|---|---|
| `raw.json`、`parsed.md` | 原 OCR 結果的副本；Markdown 不作為唯一 LLM 輸入 |
| `ocr_blocks.json` | 真正送入 LLM 的 OCR 區塊 |
| `llm_request.json` | 模型、prompt、schema 與完整 API body，不含 key |
| `llm_response.json` | 成功的原始 provider JSON，包含欄位、引用與用量；HTTP 錯誤只保存安全診斷 |
| `extracted.json` | 通過格式驗證的 15 欄結果 |
| `validation.json` | JSON、型別、日期及 schema 檢查 |
| `review.json` | 缺值、來源引文或金額門檻不一致等人工確認事項 |
| `manifest.json` | 狀態、來源、雜湊、請求／回傳模型、耗時、token 用量 |

`manifest.generation.usage` 記錄 provider 回傳的 input/output/total tokens，以及有回傳時的
cached/reasoning tokens。不把 token 用量直接宣稱為帳單美元金額；價格、快取、稅費等需另核對。
`store=false` 是 Responses 儲存設定，不代表所有供應商日誌／保留政策都變成零保留。
原始回應若回顯 key、超過大小限制或不是可安全解析 JSON，只保存固定診斷。

## 4. Prompt 與 Python 的角色

- `app/extraction/block_contract.py`：GPT 與 Gemini 共用的英文 SYSTEM prompt、15 欄
  schema、OCR 區塊整理、非改值驗證。既有 Gemini prompt 文字不變。
- `app/openai_extraction/contract.py`：包裝成 Responses API 請求，strict JSON Schema、
  `store=false`、不開啟任何工具、預設 reasoning effort `none`。
- `app/openai_extraction/client.py`：HTTPS、回應解析、用量與安全錯誤分類。
- `app/openai_extraction/pipeline.py`：來源重用、新 run、結果及 manifest 保存。
- `app/extraction/ocr_artifacts.py`：GPT／Gemini 共用的原 OCR 雜湊驗證。
- `app/cli.py`：`--extractor openai` 入口，先處理 OpenAI，無需 Qwen 環境／權重。

Python 不用舊 matching rules 補值，不重算／替換 >=1000 flag。格式合法但引文可疑的值
仍保留，標記 `completed_needs_review`。格式不合法、拒答、token 截斷或 HTTP 失敗時，
標記 failed，不產生 extracted.json。來源引文檢查僅確認引用存在，不能證明語意正確。
`semantic_accuracy_verified` 維持 false，需與 ground truth 比對。

Qwen 仍使用自己原有的 Markdown prompt／contract；本次只對齊 GPT 與 Gemini。
目前不能把 Qwen 與這兩個 cloud pipeline 的差異全歸因於模型能力。

## 5. 設定與錯誤

| 變數 | 預設 |
|---|---|
| `OPENAI_API_KEY` | 無，必填 |
| `OPENAI_MODEL` | `gpt-6-luna` |
| `OPENAI_TIMEOUT_SECONDS` | 180；允許 1–600 |
| `OPENAI_MAX_OUTPUT_TOKENS` | 8192；允許 512–32768 |
| `OPENAI_REASONING_EFFORT` | `none`；也可明確選 low/medium/high，需模型支援 |

`invalid_api_key/authentication`：檢查完整 key。
`insufficient_quota`：檢查 OpenAI billing 與額度。
`model_not_found/model_unavailable`：檢查模型 ID 與權限。
`unsupported_value/unsupported_parameter`：檢查所選模型接受的參數。
`incomplete_generation`：回應不完整；不要把部分文字當成成功結果。
`timeout`：本機等待逾時，不證明供應商未處理／未計費；沒有自動重試。
錯誤時先查看本次 `manifest.json` 與 `llm_response.json`，不要提供 API key。

## 6. 驗證範圍與官方參考

開發驗證使用 synthetic fixtures 與 HTTP MockTransport，不連線 OpenAI。
真實 key 權限、雲端 schema 接受情況、費用及收據準確率須由使用者上述 live run 確認。

- [Responses／Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
- [Responses API reference](https://developers.openai.com/api/reference/python/resources/responses)
- [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)
