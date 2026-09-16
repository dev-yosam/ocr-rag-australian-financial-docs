"""All examples below are synthetic, not captured OCR or private documents."""
from decimal import Decimal
from datetime import date
import json
import pytest
from pydantic import ValidationError
from app.core.files import json_text
from app.extraction.invoice import RuleInvoiceExtractor
from app.schemas.invoice import TaxInvoice


def extract(text):
    return RuleInvoiceExtractor().extract(text)


def test_all_fourteen_fields_from_explicit_evidence():
    result = extract("""# RECEIPT
Supplier: FAKE Supplier
Seller ABN: 00 000 000 000
Receipt No.: 0007
Issue Date: 2026-09-16
Purchase Date: 2026-09-15
Payment Due Date: 2026-09-30
Expense Type: goods
Payment Status: Paid in full
Buyer: FAKE Buyer
Taxable Sale Extent: 50%
Total (inc GST): AUD 1,000.00
GST: AUD 45.45
""")
    assert result.model_dump() == {
        "document_type": "receipt", "document_number": "0007",
        "total_cost": Decimal("1000.00"), "seller_business_name": "FAKE Supplier",
        "date_of_expense": date(2026, 9, 15), "date_of_issue": date(2026, 9, 16),
        "nature_of_expense": "goods", "paid": True,
        "is_total_cost_equal_to_or_higher_than_1000": True,
        "seller_abn": "00000000000", "gst": Decimal("45.45"),
        "payment_due_date": date(2026, 9, 30), "buyer_identity": "FAKE Buyer",
        "taxable_sale_extent": Decimal("50"),
    }


@pytest.mark.parametrize("text", [
    "Invoice Date\n2026-09-16", "**Invoice Date:** 2026-09-16",
    "Invoice Date 2026-09-16", "Invoice Date：2026-09-16",
    "| Invoice Date | 2026-09-16 |",
    "<table><tr><td>Invoice Date</td><td>2026-09-16</td></tr></table>",
    "<table><tr><td>Invoice Date<br>2026-09-16</td></tr></table>",
    "<table><tr><th>Invoice Date</th><th>Due Date</th></tr><tr><td>2026-09-16</td><td>2026-09-30</td></tr></table>",
    "| Invoice Date | Due Date |\n| --- | --- |\n| 2026-09-16 | 2026-09-30 |",
])
def test_issue_date_across_supported_layouts(text):
    assert extract(text).date_of_issue == date(2026, 9, 16)


@pytest.mark.parametrize("text", ["Date: 2026-09-16", "Due Date: 2026-09-16",
    "Invoice Date\n\n2026-09-16", "Invoice Date\nDue Date: 2026-09-16",
    "Invoice Date: 03/04/2026", "Invoice Date: 2026-09-16\nInvoice Date: 2026-09-17",
    "<script>Invoice Date: 2026-09-16</script>",
    "<table><tr><td colspan='2'>Invoice Date</td></tr><tr><td>2026-09-16</td></tr></table>"])
def test_no_unsafe_date_assignment(text):
    assert extract(text).date_of_issue is None


def test_distinct_dates_not_substituted():
    result = extract("Invoice Date: 2026-09-16\nDue Date: 2026-10-01")
    assert result.date_of_expense is None
    assert result.date_of_issue == date(2026, 9, 16)
    assert result.payment_due_date == date(2026, 10, 1)
    assert extract("Purchase Date: 2026-09-15\nPayment Date: 2026-09-16").date_of_expense is None


@pytest.mark.parametrize("amount,expected", [("999.99", False), ("1000", True), ("1000.01", True)])
def test_threshold_boundary(amount, expected):
    assert extract("Total: " + amount).is_total_cost_equal_to_or_higher_than_1000 is expected


def test_missing_conflicting_and_exclusive_totals():
    for text in ["GST: 10", "Total: 100\nTotal: 200", "Subtotal: 100", "Amount Due: 100", "Total (ex GST): 100"]:
        result = extract(text)
        assert result.total_cost is None
        assert result.is_total_cost_equal_to_or_higher_than_1000 is None


@pytest.mark.parametrize("status,expected", [("Paid in full", True), ("Unpaid", False), ("Partially paid", None), ("Pending", None)])
def test_paid_requires_explicit_status(status, expected):
    assert extract("Payment Status: " + status).paid is expected


def test_receipt_does_not_automatically_mean_paid():
    assert extract("# RECEIPT\nAmount Due: 0").paid is None
    assert extract("Paid: yes\nPayment status: unpaid").paid is None


def test_classification_is_explicit_and_conflicts_are_null():
    assert extract("# TAX INVOICE").document_type == "tax_invoice"
    assert extract("# CUSTOMER COPY").document_type == "customer_copy"
    assert extract("# RECEIPT\n# INVOICE").document_type is None
    assert extract("Please keep this receipt for your records").document_type is None
    assert extract("Expense type: goods and service").nature_of_expense is None
    assert extract("Supplier: FAKE Plumbing Service").nature_of_expense is None


def test_supplier_and_customer_scopes_in_tables():
    result = extract("<table><tr><td>Supplier</td><td>FAKE Seller</td></tr><tr><td>ABN</td><td>00 000 000 000</td></tr><tr><td>Bill To</td><td>FAKE Buyer</td></tr><tr><td>ABN</td><td>11 111 111 111</td></tr></table>")
    assert result.seller_abn == "00000000000"
    assert result.seller_business_name == "FAKE Seller"
    assert extract("Bill To:\nBusiness Name: FAKE Buyer\nABN: 11 111 111 111").seller_business_name is None


def test_taxable_percentage_requires_explicit_percent():
    assert extract("Total price includes GST").taxable_sale_extent is None
    assert extract("Taxable sale extent: 0.5").taxable_sale_extent is None
    assert extract("Taxable sale extent: 101%").taxable_sale_extent is None
    result = extract("Taxable sale extent: 12.50%")
    assert result.taxable_sale_extent == Decimal("12.50")
    assert json.loads(json_text(result.model_dump()), parse_float=Decimal)["taxable_sale_extent"] == Decimal("12.50")


@pytest.mark.parametrize("kwargs", [{"paid": "false"}, {"paid": 1},
    {"nature_of_expense": "mixed"}, {"taxable_sale_extent": "NaN"},
    {"taxable_sale_extent": "101"}, {"taxable_sale_extent": "-1"},
    {"taxable_sale_extent": 0.1}, {"total": "100"}, {"subtotal": "90"}])
def test_schema_rejects_invalid_types_ranges_and_old_keys(kwargs):
    with pytest.raises(ValidationError):
        TaxInvoice(**kwargs)


def test_next_label_without_colon_is_not_a_document_number():
    result = extract("Invoice Number\nTotal 123.00")
    assert result.document_number is None
    assert result.total_cost == Decimal("123.00")


@pytest.mark.parametrize("title,kind", [("Tax Invoice", "tax_invoice"), ("Bill", "bill"), ("Receipt", "receipt"), ("Customer Copy", "customer_copy"), ("Invoice", "invoice")])
def test_supported_document_titles(title, kind):
    assert extract("# " + title).document_type == kind


def test_empty_document_has_fourteen_null_fields():
    result = extract("")
    payload = json.loads(json_text(result.model_dump()))
    assert len(payload) == 14
    assert all(v is None for v in payload.values())
    assert TaxInvoice.model_validate(payload) == result


@pytest.mark.parametrize("separator", ["-", "–", "—", ":"])
def test_joined_document_title_and_abn(separator):
    # Independently authored fake data, not a copied private document fixture.
    result = extract(f"# TAX INVOICE {separator} ABN 00 000 000 000")
    assert result.document_type == "tax_invoice"
    assert result.seller_abn == "00000000000"


@pytest.mark.parametrize("text", [
    "Please retain TAX INVOICE - ABN 00 000 000 000",
    "TAX INVOICE - 00 000 000 000",
    "TAX INVOICE - ABN 00 000 000 000 unrelated text",
    "TAX INVOICE - ABN 00 000 000 0000",
])
def test_joined_header_does_not_extract_unlabelled_or_malformed_abn(text):
    assert extract(text).seller_abn is None


def test_joined_header_keeps_buyer_scope_and_detects_conflicts():
    result = extract("Buyer: FAKE Customer\nTAX INVOICE - ABN 11 111 111 111")
    assert result.seller_abn is None
    result = extract("TAX INVOICE - ABN 00 000 000 000\nSupplier ABN: 11 111 111 111")
    assert result.seller_abn is None
    assert extract("TAX INVOICE - Buyer ABN 11 111 111 111").seller_abn is None
    assert extract("TAX INVOICE - ABN 00 000 000 000\n# RECEIPT").document_type is None


def test_joined_header_inside_html_cell():
    result = extract("<table><tr><td>Tax Invoice - ABN 00 000 000 000</td></tr></table>")
    assert result.document_type == "tax_invoice"
    assert result.seller_abn == "00000000000"
