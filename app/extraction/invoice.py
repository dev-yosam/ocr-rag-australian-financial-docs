from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Protocol

from app.core.errors import ExtractionError
from app.schemas.invoice import TaxInvoice


class InvoiceExtractor(Protocol):
    def extract(self, document: str) -> TaxInvoice: ...


def one(values: list):
    unique = set(values)
    return unique.pop() if len(unique) == 1 else None


def parse_date(value: str) -> date | None:
    value = value.strip()
    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{4}", value):
        first, second, year = map(int, re.split(r"[/-]", value))
        if first <= 12 and second <= 12 and first != second:
            return None
        try:
            return date(year, second, first) if first > 12 or first == second else date(year, first, second)
        except ValueError:
            return None
    for pattern in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def money(value: str) -> Decimal | None:
    value = re.sub(r"^(?:AUD\s*|A\$\s*|\$\s*)", "", value.strip(), flags=re.I)
    if not re.fullmatch(r"-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?", value):
        return None
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None


def labelled_lines(markdown: str) -> list[tuple[str, str]]:
    """Read explicit labels in prose, Markdown tables, and HTML table rows."""
    from html import unescape
    text = re.sub(r"</tr\s*>", "\n", markdown, flags=re.I)
    text = re.sub(r"</t[dh]\s*>", " | ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    pairs = []
    customer_section = False
    for line in unescape(text).splitlines():
        line = re.sub(r"^\s*#+\s*", "", line)
        line = re.sub(r"[*_`]", "", line).strip().strip("|").strip()
        if re.match(r"^(customer|bill to|buyer|recipient)(?:\s*:|$)", line, re.I):
            customer_section = True
        elif re.match(r"^(supplier|seller|invoice|business name)\b", line, re.I):
            customer_section = False
        parts = re.split(r"\s*\|\s*|\s*:\s*", line, maxsplit=1)
        if len(parts) == 2:
            if customer_section and parts[0].strip().lower() == "abn":
                continue
            pairs.append((parts[0].strip().lower(), parts[1].strip().strip("|").strip()))
    return pairs


class RuleInvoiceExtractor:
    LABELS = {
        "business_name": {"supplier", "supplier name", "business name", "seller"},
        "abn": {"abn", "supplier abn", "seller abn"},
        "invoice_number": {"invoice number", "invoice no", "invoice no.", "invoice #"},
        "invoice_date": {"invoice date", "date of invoice"},
        "subtotal": {"subtotal", "sub total", "subtotal (ex gst)", "subtotal (excl. gst)"},
        "gst": {"gst", "gst (10%)", "gst amount"},
        "total": {"total", "grand total", "total (inc gst)", "total (incl. gst)"},
    }

    def extract(self, document: str) -> TaxInvoice:
        pairs = labelled_lines(document)
        # M1 is explicitly AUD-only. Do not silently relabel foreign invoices.
        if re.search(r"\b(?:USD|NZD|EUR|GBP|CAD|JPY|CNY|SGD|HKD)\b|US\$|NZ\$|[€£¥]", document, re.I):
            raise ExtractionError("Unsupported explicit currency")
        for label, value in pairs:
            if label == "currency" and value.upper() != "AUD":
                raise ExtractionError("Unsupported explicit currency")
        values = {}
        for field, labels in self.LABELS.items():
            candidates = [value for label, value in pairs if label in labels]
            if field == "invoice_date":
                candidates = [parse_date(value) for value in candidates]
            elif field in {"subtotal", "gst", "total"}:
                candidates = [money(value) for value in candidates]
            elif field == "abn":
                candidates = [re.sub(r"\s", "", value) for value in candidates]
                candidates = [value if re.fullmatch(r"[0-9]{11}", value) else None for value in candidates]
            else:
                candidates = [value if value and value.lower() not in {"n/a", "null", "unknown"} else None for value in candidates]
            values[field] = one(candidates)
        return TaxInvoice(**values)
