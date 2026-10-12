# TIRBIC extraction contract

## Current LLM contract: tirbic-15-v3 (2026-10-11)

Qwen, Gemini and GPT now use `app/schemas/tirbic_llm.py` as the single source for
the 15 field names, value validation, invoice JSON Schema and shared English field
instructions. Source: the user-supplied **labelling-standards (1).pdf**, three pages.
The user explicitly selected a **0..1 fraction** for taxable_sale_extent: 100% is
`1.0`, 75% is `0.75`. This is not the v2 rules baseline's 0..100 representation.

### Missing-value strings

All 15 keys are required. Any field can use the following exact reason strings,
including fields that otherwise contain a number, date, boolean or enum:

| Value | Meaning |
|---|---|
| `not_found` | Requested field is absent. |
| `file_quality_insufficient` | Blur, low resolution or cropping prevents extraction. |
| `cannot_be_determined` | Overall context is insufficient, ambiguous or conflicting. |

**Buyer exception:** the specific buyer_identity instruction overrides the general
not_found rule: an absent buyer is `""`. A genuinely ambiguous or unreadable buyer
can use the other two reasons. Buyer evaluation is required only when the
**ground-truth** >=1000 flag is true; a predicted false flag cannot hide a mistake.
Extraction may retain a printed buyer below the threshold.

Invoice values cannot be null. No extra per-field reason object is introduced.
The LLM response envelope contains `invoice`, `evidence`, `currency`; currency may
be null when unspecified. `extracted.json` remains the plain 15-field invoice map.
Known total_cost and gst are two-decimal JSON strings without currency symbols,
commas or spaces, e.g. "51.10", "32.00" and "0.00". Missing reasons remain unchanged.
This user-approved monetary-format revision uses provider prompt suffix v2; earlier
v3 runs with numeric money remain historical and are not edited. Invalid model formats
are rejected, not padded or rounded by Python. taxable_sale_extent stays numeric.
Known dates are YYYY-MM-DD, known flags are JSON
booleans. ABNs remain eleven-digit strings; document numbers preserve leading zeros.
Supply/category enums are unchanged from v2. Invoice number still takes priority
over receipt number for tax invoices, as previously confirmed by the user.

### Shared field semantics, different source formats

All three models use `FIELD_INSTRUCTIONS` and `invoice_schema()` from the shared
module. They preserve the model's values, including the >=1000 flag; Python never
recalculates it, fills missing values, or silently converts 100 to 1.0. Inconsistent
flags are retained with review issues. Literal validation does not establish accuracy.

Qwen still receives OCR Markdown and returns string quotations. Gemini/GPT still
receive whitelisted OCR blocks and return block_ref/quote evidence. The source
wrappers and evidence diagnostics therefore differ; prompts are not byte-identical.
This update unifies the invoice contract, not the source representation or runtimes.

These are **OCR-text-only** pipelines. Missing OCR text cannot prove that the source
document lacks a field or that an image was blurry. Do not claim visual inspection.
The prompt asks for supported reasons and abstention when absence versus OCR omission
cannot be distinguished. Every predicted reason is retained and marked for review;
the evaluator can still count an exact reason match as correct. Review is not a
ground-truth error label and does not rewrite output.

### Versions, migration and evaluation

- New LLM manifests use `schema_version=tirbic-15-v3`; provider prompt identifiers
  are v3 as well. New requests use v3 automatically with existing extractor commands.
- Old output directories remain unchanged. Re-extract verified saved OCR into a
  **new run** to obtain v3. Never relabel old nulls as not_found automatically.
- Review original annotations before converting legacy taxable percentages; 1 in
  v2 meant 1%, but 1 in v3 means 100%. No implicit scale conversion is performed.
- `scripts/evaluate_fields.py --standard-version tirbic-15-v3` compares the exact
  three reason strings and validates fractions in 0..1. Null ground truth is rejected
  in v3. Evaluation defaults to v2 for existing callers; select v3 explicitly.
- The evaluation report retains correct/incorrect/skipped counts. It does not add
  precision/recall definitions or claim accuracy without reviewed ground truth.
- Rules remain v2; pure OCR, model weights, API keys and Cetus batch jobs are unaffected.

Known-value JSON example (partial, not a complete response):

```json
{
  "total_cost": "51.10",
  "gst": "not_found",
  "paid": "cannot_be_determined",
  "buyer_identity": "",
  "taxable_sale_extent": 1.0
}
```

Structured-output schema composition follows the supported `anyOf`/enum approach
in the [OpenAI documentation](https://developers.openai.com/api/docs/guides/structured-outputs)
and [Gemini documentation](https://ai.google.dev/gemini-api/docs/structured-output).
Provider acceptance still requires a real API test; fake tests are not live validation.

## Legacy rules baseline: tirbic-15-v2

The remaining sections describe the unchanged rules baseline and historical v2 behavior,
not the current LLM contract above.

Version: `tirbic-15-v2`. Based on the user-supplied `labelling-standards.pdf`
(one page) and the accompanying client-update message. This updates the former
14-field contract. It is a local implementation, not Azure feature parity.

## Fields

All 15 keys are emitted. Unknown/conflicting values remain null, except a missing
buyer_identity is an empty string as required by the standard. No confidence or
source coordinates are fabricated.

| Field | Type | Current implementation |
|---|---|---|
| document_type | enum or null | Explicit title/type label. tax_invoice, bill, invoice outrank receipt and customer_copy. Multiple different titles within one tier remain unresolved. |
| document_number | string or null | Type-matching number; tax invoices prefer invoice number, then receipt number (user-confirmed). Generic document number and then reference number are fallback. Bill also accepts a labelled No./No fallback. Never transaction/order number. Conflicting candidates in a selected tier return null. |
| total_cost | Decimal or null | Explicit total/grand total/inclusive total; customer_copy also accepts PURCHASE. Conflicts remain null; no computed sums or amount-due substitution. |
| seller_business_name | string or null | Explicit supplier/seller labels; unlabelled company names are not inferred. |
| date_of_expense | date or null | Explicit purchase/transaction/payment date, with constrained POS timestamp fallback described below; conflicts remain unresolved. |
| date_of_issue | date or null | Explicit invoice/issue/receipt date, with constrained POS timestamp fallback described below; not a generic bare Date. |
| supply_type | enum or null | goods, services, goods_and_services, penalties. Explicit Supply Type label only. |
| expense_category | enum or null | housing, utilities, food, transportation, healthcare, debt_repayment, savings_and_investments, entertainment, personal_care, miscellaneous. Explicit Expense Category label only. |
| paid | boolean or null | Explicit paid/unpaid status or constrained POS payment evidence below. Conflicts remain null. |
| is_total_cost_equal_to_or_higher_than_1000 | boolean or null | total_cost >=1000, or null without a safe total. |
| seller_abn | string or null | Explicit ABN, eleven digits; buyer context excluded. No external verification. |
| gst | Decimal or null | Explicit GST, never calculated from total. |
| payment_due_date | date or null | Explicit payment due date, separate from other dates. |
| buyer_identity | string | Explicit buyer name/business/ABN; absent, conflicting or card-like values produce an empty string. Payment-card identifiers are excluded conservatively. |
| taxable_sale_extent | Decimal 0..100 or null | Labelled percentage, or the exact standalone example Total price includes GST -> 100. Conflicting evidence returns null. |

## Annotation conventions and limits

- The includes-GST mapping is the supplied dataset convention, not an assertion
  that every document mentioning GST is legally 100% taxable. No partial-item
  aggregation is implemented; a document-level number is retained.
- Buyer identity is evaluated only when the reference >=1000 flag is true.
  Extraction can retain identity below the threshold; evaluation skips it.
- Names plus ABNs that differ as strings are not yet merged into one identity.
- Supply/category outputs are validated enums but there is no semantic line-item
  classification model. Unknown does not default to miscellaneous.
- Dates are ISO in output. Ambiguous numerical dates remain null. Date priority
  between different purchase/payment dates is still unspecified.
- Document-number selection for an absent type uses an unambiguous explicit
  document/invoice/receipt/bill number, then reference. Conflicts return null.
- Two distinct titles within the same precedence tier remain null: the PDF
  defines inter-tier priority but not an ordering within each tier.
- Processing is still AUD-only; currency is not an output key. Decimal amounts
  are JSON numbers, with no binary-float conversion in extraction.

## Migration

`nature_of_expense` is removed, with no silent alias. New fields are supply_type
and expense_category. `services` is plural; do not reuse legacy `service` values.
Existing annotations must be independently reviewed for the two new fields;
an old goods/service value does not determine the expense category.
Missing buyer_identity changes from null to an empty string. The manifest version
changes from tirbic-14-v1 to tirbic-15-v2. Existing run artifacts are not rewritten.

Earlier key changes remain: business_name -> seller_business_name, abn ->
seller_abn, invoice_number -> document_number, invoice_date -> date_of_issue,
total -> total_cost; subtotal/currency are not output keys.
The Python TaxInvoice class name and /v1/invoices/process endpoint remain.

## Rules baseline: layout support and verification

Prose, adjacent label/value lines, simple HTML/Markdown tables, and standalone
joined title/ABN headings are supported. Complex merged rows and arbitrary
unlabelled layouts still require further work. Tests are synthetic.

Run `python -m pytest -m "not integration"`. The current branch preserves the
merged GPU configuration and does not rerun OCR or change model dependencies.
See [EVALUATION.md](EVALUATION.md) for comparisons against ground truth.


## Rules baseline: POS matching extensions (2026-09-20)

These rules are tested with manually authored synthetic text, not real PaddleOCR
output. Real image-to-JSON acceptance still requires the corresponding OCR artifacts.

- Date values accept a valid HH:MM or HH:MM:SS suffix. Invalid clocks and ambiguous
  day/month values remain null. Two-digit years explicitly mean 2000-2099; this is
  a contemporary-receipt convention, not support for historical documents.
- On customer copies, DATE/TIME supplies issue and expense dates only when their
  specific labels are absent. Explicit invalid/conflicting fields are not replaced.
- On bills, an exact combined numeric date/time + No: identifier row supplies a
  POS date for the same fallback. A generic Date elsewhere still does not suffice.
- No:/No.: identifiers are a bill-only fallback after Bill Number/Document Number;
  order numbers, TID, STAN and RRN are not promoted to document numbers.
- GST Included In Total, G.S.T Included In Total and dotted variants match GST
  amounts. This wording alone does not set taxable_sale_extent to 100.
- PURCHASE is a total candidate only for customer_copy. Conflicting totals remain null.
- Customer-copy PURCHASE with a resolved total and a standalone Approved or
  Approved 00 line supports paid=true. Standalone Declined supplies conflicting/
  negative evidence. A bill requires both EFTPOS equal to its positive total and
  Balance equal to zero before deriving paid=true. Explicit status conflicts stay null.
- Seller names without labels, supply_type and expense_category are still not
  inferred from merchant names or logos. No merchant-specific lookup was added.

Legacy annotations using nature_of_expense and fractional taxable_sale_extent
must be reviewed before 15-field evaluation. No automatic legacy conversion or
claim of a full match is made. Real samples and ground truth are not committed.

## Historical local LLM extraction (2026-09-20; superseded for new runs)

`--extractor llm` selects Qwen3-4B-Instruct-2507 to interpret OCR Markdown and
populate this same 15-field schema. It can propose unlabelled merchant names and
supply/expense classifications from context. These are model predictions needing
evaluation, not a change to field definitions or proof of accuracy. The rules
baseline's label/line-adjacency limitations above do not describe the LLM strategy.

Python validates all values, source quotations, dates and monetary types and
recomputes the threshold flag. It does not run the rule extractor as a fallback.
No new confidence score or silent legacy ground-truth conversion is introduced.
See [local LLM usage](LLM.md) for evidence artifacts, CPU/GPU setup and limitations.

## Historical Gemini cloud extraction (2026-10-07; superseded for new runs)

`extract --extractor gemini` uses the same 15 fields, but the LLM receives all
Paddle parsing blocks including headers/footers, rather than just Markdown.
This strategy does not use the rules baseline's matching restrictions. Python
checks basic types/formats and quote presence without filling or changing values.
Unlike the Qwen implementation above, it does NOT recompute the >=1000 flag:
inconsistency is retained and reported in review.json. Quotes are not proof of
semantic support. See [Gemini usage](GEMINI_ZH_TW.md) for prompt, privacy and limits.
