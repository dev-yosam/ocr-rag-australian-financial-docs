# Provisional TIRBIC extraction contract

Version: `tirbic-14-v1`. Based on the 14 fields provided by the project team.
This document describes our local implementation, not Azure feature parity.
The Azure analyzer configuration and its completion/embedding models are not
loaded or called. Client field definitions remain subject to review.

All 14 keys are emitted. Unknown, invalid or conflicting evidence is null.
No source confidence is fabricated. Examples and automated tests are synthetic.

| Field | Type | Current evidence/rule |
|---|---|---|
| document_type | enum or null | Exact standalone title, standalone title joined to a labelled ABN, or Document Type label: tax_invoice, bill, receipt, customer_copy, invoice. Conflicting titles return null; no semantic inference. |
| document_number | string or null | Explicit document/invoice/receipt/bill number; leading zeros retained. |
| total_cost | Decimal or null | Explicit total/grand total/inclusive total; never subtotal, amount due or computed sum. Generic total is provisionally accepted, without proving GST treatment. |
| seller_business_name | string or null | Explicit supplier/seller name. Unlabelled logos and company headers are not inferred. |
| date_of_expense | date or null | Explicit purchase/transaction/payment date. Different candidate dates return null. |
| date_of_issue | date or null | Explicit issue/invoice/receipt date. Bare Date is not assigned. |
| nature_of_expense | goods/service or null | Explicit Nature of Expense or Expense Type label only. No classification of line items yet. |
| paid | boolean or null | Explicit paid/unpaid status; no inference from document type, zero balance or partial payment. |
| is_total_cost_equal_to_or_higher_than_1000 | boolean or null | Derived total_cost >= 1000; null without a safe total. |
| seller_abn | string or null | Labelled seller ABN, or ABN outside buyer section; 11 digits, no checksum or external lookup. |
| gst | Decimal or null | Explicit GST value, never inferred from total. |
| payment_due_date | date or null | Explicit due date; separate from issue and expense dates. |
| buyer_identity | string or null | Explicit buyer/customer identity or ABN. Multiple distinct values currently return null, even when name and ABN may refer to the same buyer. |
| taxable_sale_extent | Decimal 0..100 or null | Explicit labelled percentage only, no inference from a GST amount or includes-GST wording. |

## Decisions awaiting client confirmation

- Threshold: field name specifies >=1000, while the supplied description says
  higher than 1000. Implementation provisionally follows the field name.
- Expense date: no priority is chosen between different purchase/payment dates.
- Paid: partial, unknown and contradictory statuses return null, not false.
- Nature: mixed goods/services return null; line-item semantic classification is
  not implemented. A future strategy may be needed for the supplied infer rule.
- Taxable extent: the local contract is one document-level percentage. Per-sale
  percentages require an agreed aggregation or a line-item schema. The supplied
  includes-GST example is not treated as sufficient evidence of 100% taxable.
- Total cost: generic Total is accepted as a candidate but tax inclusion cannot
  always be established from that label. Mixed tax treatment needs review.
- No currency output key was supplied. Processing remains AUD-only and rejects
  explicit foreign currencies. A multi-currency contract needs a separate change.

## Breaking migration from the original prototype

| Original key | New key |
|---|---|
| business_name | seller_business_name |
| abn | seller_abn |
| invoice_number | document_number |
| invoice_date | date_of_issue |
| total | total_cost |
| gst | gst |
| document_type | document_type, now nullable and supports five classes |
| subtotal / currency | Removed from output |

Legacy input keys are rejected by schema validation, not silently aliased.
The Python class name TaxInvoice and API path /v1/invoices/process are retained
for now; API/CLI invoice payloads have the new 14 keys. Consumers must migrate.
Old artifacts are not rewritten. New processing manifests include schema_version.

## Verification

Run `python -m pytest -m "not integration"`. Tests cover independent expected
fields, tables, neighbouring lines, seller/buyer separation, three date meanings,
ambiguous dates, strict booleans, exact Decimal JSON numbers and the 1000 boundary.
Model weights and OCR dependencies are unchanged. Passing extraction tests does
not demonstrate complete accuracy on real receipts or new GPU compatibility.

## Joined title/ABN handling

A standalone heading such as `TAX INVOICE - ABN 00 000 000 000` is split into
an explicit title and ABN pair. This example is synthetic. The ABN must still
have exactly eleven digits; buyer context, trailing unrelated text and
conflicting ABNs do not silently produce a seller ABN. This is not a general
search for arbitrary eleven-digit numbers or company names.
