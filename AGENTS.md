# Engineering rules

Build a local-first Australian financial Document AI pipeline incrementally.
PaddleOCR-VL-1.6 (the complete layout + recognition pipeline) is required; never
silently substitute another OCR system. Keep parsing, field extraction, Pydantic
validation, and the RAGFlow HTTP adapter separate. RAGFlow owns chunking,
embeddings, storage, retrieval, and RAG orchestration. Do not reimplement them.
Milestone 1 covers one synthetic tax invoice; no fine-tuning, UI, authentication
system, bank statements, tax returns, or production deployment.

Work only in this repository. Never inspect personal accounts, credentials,
unrelated environment variables, other repositories, or personal files. Public
technical documentation is allowed. Synthetic financial fixtures only. Never
upload documents to external services. Never log document contents or secrets.

User-approved exception: real invoice photos explicitly placed by the user in
`private_inputs/` may be processed locally for OCR and field extraction only.
Keep inputs and results ignored by Git and private inputs excluded from Docker
build context. Do not send these documents or their derived content to RAGFlow
or any external service. Automated tests and shared fixtures remain synthetic.
Keep models, caches, temporary files, and runtime data inside ignored directories
here. `.env.example` contains empty variable assignments only; never commit `.env`.

The user controls Git history. Do not add, commit, push, merge, rebase, tag, reset,
clean, switch branches, or create pull requests. Do not initialize Git. Read-only
status/diff/log commands are allowed. Finish by reporting changed files, changes,
test commands/results, and blockers, then stop.

Prefer typed small functions, explicit interfaces, dependency injection at external
boundaries, pinned dependencies, deterministic behavior, and sanitized exceptions.
Do not invent missing fields or confidence scores. Preserve raw provider output.
No automatic network access during processing; download models explicitly first.

Tests: `python -m pytest -m "not integration"`; real OCR:
`python -m pytest -m paddleocr_integration`; self-hosted RAGFlow:
`python -m pytest -m ragflow_integration`. Integration tests are opt-in via
RUN_PADDLEOCR_INTEGRATION / RUN_RAGFLOW_INTEGRATION. Missing services are blockers,
not evidence of success. Verify against official documentation before changing
dependencies or provider contracts.

User-approved schema extension: align local extraction with the supplied 15-field
TIRBIC contract for tax invoices, bills, receipts, customer copies and invoices.
Use docs/TIRBIC_SCHEMA.md for provisional semantics and pending client decisions.
Keep synthetic tests and private-data restrictions in force. GPU and RAGFlow
runtime deployment are not part of this schema change.

The user-supplied labelling-standards.pdf supersedes the previous 14-field schema.
Use tirbic-15-v2; nature_of_expense is removed. The user explicitly authorized
creation of feat/update-labelling-standards for this update; commit/push remain
user-controlled. Invoice number takes priority over receipt number for tax
invoices by explicit user clarification. Preserve merged GPU configuration.

User-approved runtime extension: create feat/cpu-gpu-dual-mode and support explicit
CPU or GPU selection. Default local settings to CPU; preserve GPU dependency recipe
and GPU Compose service. Never silently fall back. Commit/push remain user-controlled.

User-approved LLM extension: keep the rules baseline and add explicit offline
Qwen3-4B-Instruct-2507 extraction on Windows CPU and Cetus GPU. Use identical
pinned model weights, a separate PyTorch environment, and the 15-field contract
with source-evidence review. Prepare models explicitly; no cloud API, secret, automatic download,
or fallback during inference. Keep prompts/responses private and hashed. Replaying
existing OCR must create a new run and verify source-artifact hashes. This does
not authorize uploading private receipts to Cetus or changing Git history.

使用者已核准的 LLM 驗證調整：由 Qwen 配對欄位，不用舊 matching 規則補值。
JSON 結構、欄位型別、合法日期、enum、有限金額及 AUD 限制仍須通過基本驗證；
來源證據缺失、不符或無法支持欄位值，改列逐欄人工確認事項，不因此丟棄整份結果。
可折疊無語意差異的空白，但須保留詞與數字間的分隔，不可把分離的數字合併。
將疑問與缺值寫入私有 review.json；需要確認時使用 completed_needs_review，
無確認事項時使用 completed。兩者均不保證內容正確；semantic_accuracy_verified
維持 false，準確率須另以人工 ground truth 評估。CPU/GPU 共用此處理契約。

User reporting preference: write all test and evaluation reports in Traditional
Chinese, including findings, limitations, and next steps. Preserve code, commands,
model names, filenames, and machine-readable schema keys verbatim.

使用者核准的純 OCR 階段：提供單文件 `parse`，僅執行完整 DocLayoutV3＋VL-1.6，
不建構 rules／Qwen 抽取器、不要求 LLM 環境。成功保存 raw.json、parsed.md、
manifest.json，使用 mode=ocr_only 及獨立 ocr_status；無 extracted.json 是正常行為。
本階段不包含批次、畫框／裁切圖、HTML 預覽、YAML 設定或新的 Cetus 部署。
private_inputs/ocr_batch10 的使用者資料可在本機檢查；測試 fixtures 維持合成資料。

使用者核准的 Gemini 擴充（2026-10-07）：新增明確選用的
`extract ... --extractor gemini`，呼叫 Google Gemini API 的
`gemini-3.5-flash-lite`，重用已核對雜湊的 Paddle parsing blocks。
這是上述禁止雲端服務的限定例外：只有使用者明確選用該指令時，才傳送 OCR
區塊文字／座標，不傳圖片、PDF、本機路徑或整份原始 provider metadata。
實作、文件與 fake tests 不授權 agent 自行上傳真實資料；live test 仍需使用者
設定 key 並指定要測試的資料。`--dry-run` 完全離線、不需 key。
不得讀取、輸出、提交 key；只從指定 GEMINI_API_KEY 取得，使用 HTTPS header，
不寫入 request/manifest/log。Gemini 的 key、模型及連線不影響 parse/rules/Qwen。
Gemini 只做模型欄位抽取與非修改式格式驗證／證據複核；不得調用 matching 規則，
不得重新計算並覆寫任何模型欄位（包含 >=1000 flag），不得默默 fallback 或重試。
保留原始回答與驗證結果；型別不合法或回答截斷不得產生 extracted.json。

使用者另核准測試 `gemini-flash-lite-latest`：可用 GEMINI_MODEL 明確選擇此 alias
或原本 gemini-3.5-flash-lite，預設維持原模型；不自動 fallback。manifest 記錄
請求模型及 provider 有提供時的 modelVersion。latest 不是固定版本，不宣稱它等於
使用者舊程式當時使用的模型。API key 不變，不增加雲端呼叫次數。
