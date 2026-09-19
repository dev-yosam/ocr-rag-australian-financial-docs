# TIRBIC extraction contract

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
| document_number | string or null | Type-matching number; tax invoices prefer invoice number, then receipt number (user-confirmed). Generic document number and then reference number are fallback. Never transaction/order number. Conflicting candidates in a selected tier return null. |
| total_cost | Decimal or null | Explicit total/grand total/inclusive total; no computed sums or amount-due substitution. |
| seller_business_name | string or null | Explicit supplier/seller labels; unlabelled company names are not inferred. |
| date_of_expense | date or null | Explicit purchase/transaction/payment date; conflicting dates remain unresolved. |
| date_of_issue | date or null | Explicit invoice/issue/receipt date, not a bare Date. |
| supply_type | enum or null | goods, services, goods_and_services, penalties. Explicit Supply Type label only. |
| expense_category | enum or null | housing, utilities, food, transportation, healthcare, debt_repayment, savings_and_investments, entertainment, personal_care, miscellaneous. Explicit Expense Category label only. |
| paid | boolean or null | Explicit paid/unpaid status. Partial/unknown states remain null. |
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

## Layout support and verification

Prose, adjacent label/value lines, simple HTML/Markdown tables, and standalone
joined title/ABN headings are supported. Complex merged rows and arbitrary
unlabelled layouts still require further work. Tests are synthetic.

Run `python -m pytest -m "not integration"`. The current branch preserves the
merged GPU configuration and does not rerun OCR or change model dependencies.
See [EVALUATION.md](EVALUATION.md) for comparisons against ground truth.
