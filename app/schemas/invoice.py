from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Money = Annotated[Decimal, Field(allow_inf_nan=False, max_digits=18, decimal_places=2)]


class TaxInvoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: Literal["tax_invoice"] = "tax_invoice"
    business_name: str | None = None
    abn: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    subtotal: Money | None = None
    gst: Money | None = None
    total: Money | None = None
    currency: Literal["AUD"] = "AUD"

    @field_validator("abn")
    @classmethod
    def abn_shape(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != 11 or not value.isascii() or not value.isdigit()):
            raise ValueError("ABN must contain eleven digits")
        return value

    @field_validator("subtotal", "gst", "total", mode="before")
    @classmethod
    def no_binary_float(cls, value: object) -> object:
        if isinstance(value, (float, bool)):
            raise ValueError("Money must be decimal, string, or integer")
        return value
