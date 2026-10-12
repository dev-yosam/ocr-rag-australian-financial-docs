"""Shared v3 LLM values; the v2 rules baseline remains in invoice.py."""
from datetime import date
from decimal import Decimal
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from app.schemas.invoice import SupplyType, ExpenseCategory, SUPPLY_TYPES, EXPENSE_CATEGORIES

SCHEMA_VERSION = "tirbic-15-v3"
MissingReason = Literal["not_found", "file_quality_insufficient", "cannot_be_determined"]
MISSING_REASONS = ("not_found", "file_quality_insufficient", "cannot_be_determined")
DOCUMENT_TYPES = ("tax_invoice", "bill", "receipt", "customer_copy", "invoice")
DATES = {"date_of_issue", "date_of_expense", "payment_due_date"}
MONEY_FIELDS = {"total_cost", "gst"}
MONEY_PATTERN = r"^-?(0|[1-9][0-9]{0,15})\.[0-9]{2}$"
MoneyString = Annotated[str, Field(strict=True, pattern=MONEY_PATTERN)]
NUMBERS = {"taxable_sale_extent"}
THRESHOLD = "is_total_cost_equal_to_or_higher_than_1000"
BOOLS = {"paid", THRESHOLD}
TaxableFraction = Annotated[Decimal, Field(allow_inf_nan=False, ge=0, le=1)]


def is_missing(value: object) -> bool:
    return isinstance(value, str) and (value == "" or value in MISSING_REASONS)


class TirbicLlmInvoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: Literal["tax_invoice", "bill", "receipt", "customer_copy", "invoice"] | MissingReason
    document_number: str
    total_cost: MoneyString | MissingReason
    seller_business_name: str
    date_of_expense: date | MissingReason
    date_of_issue: date | MissingReason
    supply_type: SupplyType | MissingReason
    expense_category: ExpenseCategory | MissingReason
    paid: StrictBool | MissingReason
    is_total_cost_equal_to_or_higher_than_1000: StrictBool | MissingReason
    seller_abn: str
    gst: MoneyString | MissingReason
    payment_due_date: date | MissingReason
    buyer_identity: str
    taxable_sale_extent: TaxableFraction | MissingReason

    @field_validator("*", mode="before")
    @classmethod
    def exact_types(cls, value, info):
        field = info.field_name
        if isinstance(value, str) and value in MISSING_REASONS:
            if field == "buyer_identity" and value == "not_found":
                raise ValueError("Missing buyer uses the explicit empty-string exception")
            return value
        if field in MONEY_FIELDS:
            if not isinstance(value, str) or not re.fullmatch(MONEY_PATTERN, value):
                raise ValueError("Expected amount string with exactly two decimal places")
        elif field in NUMBERS:
            if type(value) not in (int, Decimal) or not Decimal(value).is_finite():
                raise ValueError("Expected finite JSON number or missing reason")
        elif field in BOOLS:
            if type(value) is not bool:
                raise ValueError("Expected boolean or missing reason")
        elif field in DATES:
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError("Expected ISO date or missing reason")
            date.fromisoformat(value)
        elif not isinstance(value, str) or (not value.strip() and not (field == "buyer_identity" and value == "")):
            raise ValueError("Expected nonempty string")
        if field == "seller_abn" and not re.fullmatch(r"[0-9]{11}", value):
            raise ValueError("Expected eleven ABN digits")
        return value


FIELDS = tuple(TirbicLlmInvoice.model_fields)


def missing_invoice() -> dict:
    """Example only; never used to fill missing model output keys."""
    return {name: "" if name == "buyer_identity" else "not_found" for name in FIELDS}


def invoice_schema() -> dict:
    enums = {"document_type": DOCUMENT_TYPES, "supply_type": SUPPLY_TYPES,
             "expense_category": EXPENSE_CATEGORIES}
    properties = {}
    for name in FIELDS:
        spec = {"type": "number" if name in NUMBERS else "boolean" if name in BOOLS else "string"}
        reasons = list(MISSING_REASONS)
        if name in MONEY_FIELDS:
            spec["pattern"] = MONEY_PATTERN
        if name in enums:
            spec["enum"] = list(enums[name])
        if name in DATES:
            spec["format"] = "date"
        if name == "taxable_sale_extent":
            spec.update(minimum=0, maximum=1)
        if name == "seller_abn":
            spec["pattern"] = "^[0-9]{11}$"
        if name == "buyer_identity":
            reasons.remove("not_found")
        properties[name] = {"anyOf": [spec, {"type": "string", "enum": reasons}]}
    return {"type": "object", "properties": properties, "required": list(FIELDS), "additionalProperties": False}


FIELD_INSTRUCTIONS = """Contract: tirbic-15-v3. Scope: tax invoices, receipts, bills
(excluding utility bills), invoices and customer copies. All 15 fields are required.
Keep exactly these missing-value strings, including for numeric, date and boolean fields:
- not_found: the requested field is absent.
- file_quality_insufficient: blur, low resolution or cropping prevents reading the field.
- cannot_be_determined: the overall context is insufficient, ambiguous or conflicting.
Never use null for an invoice field. Missing reasons are field VALUES, not a new reason column.
You see OCR text, not original images. Absence in OCR is not proof of absence in
the original document. Use not_found only as your best supported absence assessment;
if context cannot distinguish absence from an OCR omission, use cannot_be_determined.
Do not infer file_quality_insufficient solely from missing OCR text. Without supplied
visual-quality evidence, do not claim that you inspected blur, cropping or resolution.
The application preserves your chosen reason; its correctness requires ground truth.
No confidence scores. Never invent lost text or repair values using outside knowledge.

Field definitions:
- document_type: tax_invoice, bill, receipt, customer_copy, invoice.
  Explicit tax_invoice/bill/invoice titles outrank receipt/customer_copy.
  Conflicting titles within the same tier: cannot_be_determined.
- document_number: string preserving leading zeros. Use the number corresponding
  to document_type. Tax invoices prefer invoice number, then receipt number
  (user-confirmed priority); generic document number then reference number/no. are
  fallbacks. Bill may use No:. Never use transaction/order numbers, TID, STAN or RRN.
- seller_business_name: exact merchant name from context, not bank, buyer or address;
  no guessed expansion of the printed name.
- seller_abn: seller's eleven digits as a string, remove printed spaces only.
- total_cost: printed final total including GST, or PURCHASE on customer copy.
  Do not substitute subtotal, amount due, tender or change; never sum line items.
- gst: printed GST amount only, not a computed tax or service charge.
- date_of_issue: issue date; date_of_expense: purchase/payment date;
  payment_due_date: due date. Output valid YYYY-MM-DD, keeping roles separate.
  A transaction timestamp can support both issue and expense if context supports both.
  Two-digit years mean 2000-2099. Ambiguous 03/04/26: cannot_be_determined;
  16/08/26: 2026-08-16. Never replace a date with today's date or expected ground truth.
- supply_type: goods, services, goods_and_services, penalties.
- expense_category: housing, utilities, food, transportation, healthcare,
  debt_repayment, savings_and_investments, entertainment, personal_care, miscellaneous.
  Infer both classifications conservatively from items/context. Unknown is not
  automatically miscellaneous. Quote actual source product/service words;
  an enum label is not source evidence merely because you selected that class.
- paid: JSON true/false or a missing reason. Use explicit paid/unpaid or payment
  success/decline. A total or zero balance alone does not prove payment. Matching
  EFTPOS and total plus zero balance may support true; conflicts are cannot_be_determined.
- is_total_cost_equal_to_or_higher_than_1000: total_cost >= 1000 when total is known.
  Otherwise choose a supported missing reason. YOU output the flag; Python never repairs it.
  Cite the total for this flag.
- buyer_identity: individual name, business name or ABN; never credit card numbers.
  Explicit exception: when buyer identity is not found, output "", not not_found.
  Ambiguity or evidenced poor file quality can still use the corresponding reason.
  Evaluation requires this field only if the GROUND-TRUTH >=1000 flag is true.
  You may retain a printed buyer below 1000; do not fabricate one to satisfy the dependency.
- taxable_sale_extent: numeric fraction 0..1. Convert an explicit percentage to a
  fraction: 100% => 1.0, 75% => 0.75, 0% => 0.0. Dataset convention exact statement
  'Total price includes GST' => 1.0. Other GST wording does not establish 1.0;
  never divide tax by total. Python will NOT convert 100 to 1.0 for you.
Known total_cost and gst are JSON strings with exactly two decimal places, no currency
symbols/codes, commas or spaces: 51.1 => "51.10", 32 => "32.00", 0 => "0.00".
Preserve the monetary value and any minus sign; do not round a value with more than
two nonzero decimal places. If it cannot be determined, use the appropriate missing reason.
taxable_sale_extent remains a JSON number, not a money string. This pipeline is
AUD-only: currency is AUD, another explicit code, or null if unspecified; never convert.
Python validates format and reports concerns without filling or replacing your values.
"""
