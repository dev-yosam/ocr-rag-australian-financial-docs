"""Synthetic examples for the client-provided labelling standard."""
from decimal import Decimal
import pytest
from pydantic import ValidationError
from app.extraction.invoice import RuleInvoiceExtractor
from app.schemas.invoice import TaxInvoice, SUPPLY_TYPES, EXPENSE_CATEGORIES, SCHEMA_VERSION


def extract(text):
    return RuleInvoiceExtractor().extract(text)


@pytest.mark.parametrize("value", SUPPLY_TYPES)
def test_supply_types(value):
    result = extract("Supply Type: " + value)
    assert result.supply_type == value
    assert "nature_of_expense" not in result.model_dump()


@pytest.mark.parametrize("value", EXPENSE_CATEGORIES)
def test_expense_categories(value):
    assert extract("Expense Category: " + value).expense_category == value


def test_removed_field_not_silently_migrated():
    assert extract("Nature of expense: service").supply_type is None
    assert extract("Expense type: goods").expense_category is None
    with pytest.raises(ValidationError):
        TaxInvoice(nature_of_expense="goods")
    with pytest.raises(ValidationError):
        TaxInvoice(supply_type="service")
    with pytest.raises(ValidationError):
        TaxInvoice(expense_category="other")
    assert SCHEMA_VERSION == "tirbic-15-v2"


def test_no_guessed_classification():
    result = extract("Supplier: FAKE Plumbing\nDescription: Repair service")
    assert result.supply_type is None
    assert result.expense_category is None
    assert extract("Supply Type: services\nSupply Type: goods").supply_type is None


@pytest.mark.parametrize("high", ["TAX INVOICE", "BILL", "INVOICE"])
@pytest.mark.parametrize("low", ["RECEIPT", "CUSTOMER COPY"])
def test_document_precedence(high, low):
    assert extract(f"# {low}\n# {high}").document_type == high.lower().replace(" ", "_")
    assert extract(f"# {high}\n# {low}").document_type == high.lower().replace(" ", "_")


def test_same_tier_conflict_is_unresolved():
    assert extract("# BILL\n# INVOICE").document_type is None
    assert extract("# RECEIPT\n# CUSTOMER COPY").document_type is None


@pytest.mark.parametrize("kind,labels,expected", [
    ("TAX INVOICE", "Invoice No.: I-001\nReceipt No.: R-002", "I-001"),
    ("TAX INVOICE", "Receipt No.: R-002\nReference No.: REF-003", "R-002"),
    ("RECEIPT", "Invoice No.: I-001\nReceipt No.: R-002", "R-002"),
    ("BILL", "Invoice No.: I-001\nBill Number: B-002", "B-002"),
    ("INVOICE", "Receipt No.: R-002\nReference Number: REF-003", "REF-003"),
    ("CUSTOMER COPY", "Reference #: 00 01", "0001"),
    ("INVOICE", "Transaction number: 123\nOrder number: 456", None),
    ("TAX INVOICE", "Invoice No.: 001\nInvoice No.: 002\nReference No.: 003", None),
])
def test_number_selection(kind, labels, expected):
    assert extract(f"# {kind}\n{labels}").document_number == expected


@pytest.mark.parametrize("text", ["", "Buyer: Visa 4111 1111 1111 1111", "Buyer: **** **** **** 1234", "Buyer: 4111111111111111", "Credit Card: 4111111111111111"])
def test_missing_buyer_and_card_exclusion(text):
    assert extract(text).buyer_identity == ""


def test_buyer_names_and_abns_are_retained():
    assert extract("Buyer: FAKE Buyer").buyer_identity == "FAKE Buyer"
    assert extract("Buyer ABN: 00 000 000 000").buyer_identity == "00 000 000 000"


def test_percentage_annotation_convention_and_conflicts():
    assert extract("Total price includes GST").taxable_sale_extent == Decimal("100")
    assert extract("Total price includes GST\nTaxable sale extent: 50%").taxable_sale_extent is None
    assert extract("Total price includes GST\nTaxable sale extent: 100%").taxable_sale_extent == Decimal("100")
    assert extract("Total price does not include GST").taxable_sale_extent is None
    assert extract("Some items: total price includes GST").taxable_sale_extent is None
