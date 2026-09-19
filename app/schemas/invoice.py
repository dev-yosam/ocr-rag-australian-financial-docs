"""Provisional 15-field TIRBIC output contract (not an Azure analyzer config)."""
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

SCHEMA_VERSION = "tirbic-15-v2"
Money = Annotated[Decimal, Field(allow_inf_nan=False, max_digits=18, decimal_places=2)]
SUPPLY_TYPES = ("goods", "services", "goods_and_services", "penalties")
EXPENSE_CATEGORIES = (
    "housing", "utilities", "food", "transportation", "healthcare",
    "debt_repayment", "savings_and_investments", "entertainment",
    "personal_care", "miscellaneous",
)
SupplyType = Literal["goods", "services", "goods_and_services", "penalties"]
ExpenseCategory = Literal[
    "housing", "utilities", "food", "transportation", "healthcare",
    "debt_repayment", "savings_and_investments", "entertainment",
    "personal_care", "miscellaneous",
]
Percentage = Annotated[Decimal, Field(allow_inf_nan=False, ge=0, le=100)]


class TaxInvoice(BaseModel):
    # Retain the Python class name for callers; serialized keys intentionally change.
    model_config = ConfigDict(extra="forbid")

    document_type: Literal["tax_invoice", "bill", "receipt", "customer_copy", "invoice"] | None = None
    document_number: str | None = None
    total_cost: Money | None = None
    seller_business_name: str | None = None
    date_of_expense: date | None = None
    date_of_issue: date | None = None
    supply_type: SupplyType | None = None
    expense_category: ExpenseCategory | None = None
    paid: StrictBool | None = None
    is_total_cost_equal_to_or_higher_than_1000: StrictBool | None = None
    seller_abn: str | None = None
    gst: Money | None = None
    payment_due_date: date | None = None
    buyer_identity: str = ""
    taxable_sale_extent: Percentage | None = None

    @field_validator("seller_abn")
    @classmethod
    def abn_shape(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != 11 or not value.isascii() or not value.isdigit()):
            raise ValueError("ABN must contain eleven digits")
        return value

    @field_validator("total_cost", "gst", "taxable_sale_extent", mode="before")
    @classmethod
    def no_binary_float(cls, value: object) -> object:
        if isinstance(value, (float, bool)):
            raise ValueError("Numbers must be decimal, string, or integer")
        return value
