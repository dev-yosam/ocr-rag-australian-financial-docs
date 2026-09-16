from datetime import date
from decimal import Decimal
import json

import pytest
from pydantic import ValidationError

from app.core.errors import ExtractionError
from app.core.files import json_text
from app.extraction.invoice import RuleInvoiceExtractor, money, parse_date
from app.schemas.invoice import TaxInvoice


def test_missing_fields_are_serialized_null():
    value = json.loads(json_text(TaxInvoice().model_dump()))
    assert len(value) == 14
    assert value["total_cost"] is None
    assert value["date_of_issue"] is None
    assert value["document_type"] is None


@pytest.mark.parametrize("value", [float("nan"), "NaN", "Infinity", "-Infinity", True, 0.1])
def test_invalid_money(value):
    with pytest.raises(ValidationError):
        TaxInvoice(total_cost=value)


@pytest.mark.parametrize("kwargs", [{"date_of_issue": "2026-02-30"}, {"currency": "USD"},
                                      {"document_type": "bank_statement"}, {"seller_abn": "123"}, {"extra": "x"}])
def test_invalid_schema(kwargs):
    with pytest.raises(ValidationError):
        TaxInvoice(**kwargs)


def test_decimal_json_preserves_exact_numeric_value():
    value = TaxInvoice(total_cost=Decimal("9999999999999999.99"), date_of_issue=date(2026, 9, 11))
    serialized = json_text(value.model_dump())
    assert '"total_cost": 9999999999999999.99' in serialized
    decoded = json.loads(serialized, parse_float=Decimal)
    assert decoded["total_cost"] == value.total_cost
    assert TaxInvoice.model_validate(decoded) == value


@pytest.mark.parametrize("text,expected", [("03/04/2026", None), ("31/02/2026", None),
    ("13/09/2026", date(2026, 9, 13)), ("09/13/2026", date(2026, 9, 13)),
    ("2026-09-11", date(2026, 9, 11)), ("11 September 2026", date(2026, 9, 11))])
def test_safe_dates(text, expected):
    assert parse_date(text) == expected


def test_fake_invoice_matches_independent_expected(fake_markdown):
    from tests.conftest import ROOT
    expected = json.loads((ROOT / "samples/tax_invoices/expected.json").read_text(), parse_float=Decimal)
    actual = RuleInvoiceExtractor().extract(fake_markdown)
    assert json.loads(json_text(actual.model_dump()), parse_float=Decimal) == expected


def test_no_inference_and_conflicts():
    result = RuleInvoiceExtractor().extract("Subtotal: 100.00\nCustomer: Customer Co\nTotal: 110\nTotal: 120")
    assert result.gst is None
    assert result.total_cost is None
    assert result.seller_business_name is None


def test_customer_abn_is_not_supplier_abn():
    result = RuleInvoiceExtractor().extract("Customer: Buyer Co\nABN: 11 111 111 111\nInvoice Number: 001")
    assert result.seller_abn is None
    assert result.document_number == "001"


def test_invoice_hash_label():
    assert RuleInvoiceExtractor().extract("Invoice #: 001").document_number == "001"


def test_table_and_supplier_customer():
    result = RuleInvoiceExtractor().extract("| Supplier | Seller Co |\n| Customer | Buyer Co |\n| Total | AUD 110.00 |")
    assert result.seller_business_name == "Seller Co"
    assert result.total_cost == Decimal("110.00")
    html = RuleInvoiceExtractor().extract("<table><tr><td>GST</td><td>10.00</td></tr></table>")
    assert html.gst == 10


@pytest.mark.parametrize("text", ["Currency: USD", "Total: EUR 12", "Currency: INR"])
def test_foreign_currency_rejected(text):
    with pytest.raises(ExtractionError):
        RuleInvoiceExtractor().extract(text)


@pytest.mark.parametrize("value", ["1,23.00", "1 2.00", "12.345", "not known"])
def test_amount_is_not_guessed(value):
    assert money(value) is None
