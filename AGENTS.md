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

User-approved schema extension: align local extraction with the supplied 14-field
TIRBIC contract for tax invoices, bills, receipts, customer copies and invoices.
Use docs/TIRBIC_SCHEMA.md for provisional semantics and pending client decisions.
Keep synthetic tests and private-data restrictions in force. GPU and RAGFlow
runtime deployment are not part of this schema change.
