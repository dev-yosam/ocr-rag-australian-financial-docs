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
