"""SYNTHETIC text layouts, not captured PaddleOCR results or private ground truth."""
from datetime import date
from decimal import Decimal
import pytest
from app.extraction.invoice import RuleInvoiceExtractor, parse_date


def extract(text):
    return RuleInvoiceExtractor().extract(text)


@pytest.mark.parametrize("label", ["GST Included In Total", "G.S.T Included In Total", "G.S.T. Included In Total"])
def test_gst_alias(label):
    result = extract(f"BILL\nTotal: $36.30\n{label}: $3.30\nBalance: $0.00")
    assert result.gst == Decimal("3.30")
    assert result.total_cost == Decimal("36.30")
    assert result.taxable_sale_extent is None


def test_bill_number_and_timestamp_not_order_number():
    result = extract("BILL\nYour order number is\n0042\n22/09/2026 13:10:35 No: 0098765432\nTotal: $36.30")
    assert result.document_number == "0098765432"
    assert result.date_of_issue == date(2026, 9, 22)
    assert result.date_of_expense == date(2026, 9, 22)


def test_customer_copy_transaction():
    result = extract("CUSTOMER COPY\nTID 11112222\nDATE/TIME 22/09/26 08:45\nRRN 888811112222\nPURCHASE AUD 175.00\nApproved 00")
    assert result.total_cost == Decimal("175.00")
    assert result.document_number is None
    assert result.date_of_expense == date(2026, 9, 22)
    assert result.date_of_issue == date(2026, 9, 22)


def test_context_and_conflicts():
    assert extract("INVOICE\nPurchase AUD 90.00").total_cost is None
    assert extract("CUSTOMER COPY\nNo: 1234").document_number is None
    assert extract("BILL\nNo: 1234\nNo: 5678").document_number is None
    assert extract("CUSTOMER COPY\nTotal: 90.00\nPurchase AUD 91.00").total_cost is None
    assert extract("CUSTOMER COPY\nDATE/TIME 22/09/26 08:45\nDATE/TIME 23/09/26 08:45").date_of_issue is None
    assert extract("BILL\nDate: 22/09/2026").date_of_issue is None


@pytest.mark.parametrize("value", ["03/04/26 08:45", "22/09/26 25:00", "31/02/26", "22/09/26 08:45 noise"])
def test_unsafe_dates(value):
    assert parse_date(value) is None


def test_explicit_date_not_overwritten():
    result = extract("CUSTOMER COPY\nIssue date: 21 September 2026\nDATE/TIME 22/09/26 08:45")
    assert result.date_of_issue == date(2026, 9, 21)
    assert result.date_of_expense == date(2026, 9, 22)


def test_table_timestamp_and_gst():
    result = extract("CUSTOMER COPY\n| DATE/TIME | 22/09/26 08:45 |\n| PURCHASE | AUD 175.00 |\n| G.S.T Included In Total | $3.30 |")
    assert result.total_cost == Decimal("175.00")
    assert result.date_of_issue == date(2026, 9, 22)
    assert result.gst == Decimal("3.30")


def test_payment_evidence_and_conflicts():
    assert extract("CUSTOMER COPY\nPurchase AUD 175.00\nApproved 00").paid is True
    assert extract("CUSTOMER COPY\nPurchase AUD 175.00\nApproved 00\nPaid: no").paid is None
    assert extract("CUSTOMER COPY\nPurchase AUD 175.00\nApproved 00\nDeclined").paid is None
    assert extract("CUSTOMER COPY\nApproved 00").paid is None
    assert extract("BILL\nTotal: 36.30\nEFTPOS: 36.30\nBalance: 0.00").paid is True
    assert extract("BILL\nTotal: 36.30\nBalance: 0.00").paid is None
    assert extract("BILL\nTotal: 36.30\nEFTPOS: 20.00\nBalance: 0.00").paid is None
    assert extract("BILL\nTotal: 36.30\nEFTPOS: 36.30\nBalance: 0.00\nPaid: no").paid is None
