# Offline evaluation: labelling-standards.pdf

This implements the one-page user-provided evaluation standard plus its
not-found clarification. `app/evaluation/fields.py` is independent of OCR/GPU,
RAGFlow and network services. No private document values appear in reports/logs.

## Inputs

Reference: a plain map of current 15-field names to reviewed ground-truth values.
Explicit null means not found. Empty buyer_identity also means not found.
Omitted reference keys mean unannotated, so they are NOT counted as correct.
Prediction: plain extracted.json by default; with --prediction-format azure,
a single Azure field map or {"fields": field_map}. An Azure field may use one of
valueString/valueDate/valueNumber/valueInteger/valueBoolean and optional source.
Do not pass a whole batch analysis response or a Label Studio export directly.
Legacy/unknown field names fail validation instead of being silently dropped.

## Comparison rules

| Field | Comparison |
|---|---|
| document_type | Case-insensitive; remove whitespace and underscores. |
| document_number | Exact after removing whitespace; preserve leading zeros. |
| seller_abn | Exact eleven digits after removing whitespace. |
| total_cost, gst | Exact Decimal value; allow dollar sign/AUD and valid comma grouping. Other currencies are not silently converted. |
| date_of_expense, date_of_issue, payment_due_date | Normalize supported unambiguous dates to calendar dates. |
| seller_business_name | Exact string, case-sensitive. |
| supply_type, expense_category | Exact enum value. |
| paid, >=1000 flag | Exact boolean; numeric zero/one or string booleans are not coerced. |
| buyer_identity | Exact value only when the reference >=1000 flag is true. |
| taxable_sale_extent | Exact number, no tolerance or fraction/percentage conversion. |

The PDF leaves some evaluation cells blank. This implementation uses exact enum
matching for expense_category, exact string matching for buyer_identity, and
date normalization for payment_due_date. These extensions are explicit here.

Buyer dependency comes from ground truth, never the predicted flag; an incorrect
predicted threshold cannot hide a missing buyer. Reference false skips buyer as
not_applicable; missing/null reference threshold skips it as dependency_unknown.

For expected not-found fields, plain missing/null/empty-string predictions pass.
For Azure, neither source nor a populated typed value may be present. Missing,
null and empty source/valueString are treated as absent. The PDF mentions
valueString; we additionally check other typed values so 0 and false cannot be
mistaken for absence. A source with no value still fails the not-found test.
This does not mean missing predictions pass when a ground-truth value exists.

## Usage

```powershell
python scripts/evaluate_fields.py --expected samples/tax_invoices/expected.json --predicted outputs/YOUR_RUN/extracted.json --run-id eval-01
python scripts/evaluate_fields.py --expected private_inputs/reviewed-fields.json --predicted private_inputs/azure-fields.json --prediction-format azure --run-id eval-azure-01
```

Use only approved local inputs. These are example paths, not supplied datasets.
Reports are saved in outputs/<run-id>/evaluation.json plus review.json with input
and report hashes. No OCR is run and no service is called. Existing output folders
are never overwritten. These reports cannot be used as RAG submission manifests.

Each field reports correct/incorrect/not_annotated/not_applicable/dependency_unknown.
Totals distinguish evaluated and skipped fields. They do not claim OCR character
accuracy, text-box IoU, dataset-level accuracy or inference speed. No 138-file
batch or Label Studio migration has been run or implemented here.
