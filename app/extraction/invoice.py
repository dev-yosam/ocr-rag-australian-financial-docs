from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Protocol

from app.core.errors import ExtractionError
from app.schemas.invoice import TaxInvoice, SUPPLY_TYPES, EXPENSE_CATEGORIES
from app.extraction.structure import document_rows, label, labelled_pairs


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


LABELS = {
    "seller_business_name": {"supplier", "supplier name", "business name", "seller", "seller name", "seller business name"},
    "seller_abn": {"abn", "supplier abn", "seller abn", "a.b.n."},
    "document_number": {"invoice number", "invoice no", "invoice no.", "invoice #", "receipt number", "receipt no", "receipt no.", "receipt #", "document number", "bill number"},
    "date_of_issue": {"invoice date", "date of invoice", "issue date", "date issued", "date of issue", "receipt date"},
    "date_of_expense": {"date of expense", "purchase date", "transaction date", "payment date", "date paid"},
    "gst": {"gst", "gst (10%)", "gst amount", "total gst"},
    "total_cost": {"total", "grand total", "total (inc gst)", "total (incl. gst)", "total incl gst", "total including gst", "total cost"},
    "payment_due_date": {"payment due date", "due date", "date due"},
    "buyer_identity": {"customer", "bill to", "buyer", "recipient", "buyer identity", "buyer name", "customer name", "buyer abn", "customer abn"},
    "supply_type": {"supply type"},
    "expense_category": {"expense category"},
    "paid": {"paid", "payment status", "status of payment"},
    "taxable_sale_extent": {"taxable sale extent", "taxable sale extent (%)", "taxable percentage"},
}
TITLES = {"tax invoice": "tax_invoice", "invoice": "invoice", "receipt": "receipt",
          "bill": "bill", "customer copy": "customer_copy"}

KNOWN = set().union(*LABELS.values()) | set(TITLES) | {
    "currency", "date", "subtotal", "sub total", "amount due", "balance due",
    "reference number", "reference no", "reference no.", "reference #",
    "transaction number", "transaction no", "order number", "order no",
    "nature of expense", "expense type", "document type", "name", "description", "amount", "quantity", "price", "unit price",
}


def invoice_rows(markdown: str) -> list[list[str]]:
    """Split a standalone document heading joined to an explicitly labelled ABN.

    This does not infer a seller from an arbitrary company/address line, nor
    search unlabelled digit sequences. Preserve buyer/seller section handling.
    """
    rows = []
    titles = "|".join(re.escape(title) for title in sorted(TITLES, key=len, reverse=True))
    header = re.compile(
        rf"^({titles})\s*[-–—:：|]\s*((?:(?:supplier|seller|buyer|customer)\s+)?(?:abn|a\.b\.n\.))\s*[:：]?\s+(.+)$",
        re.I,
    )
    for row in document_rows(markdown):
        match = header.fullmatch(row[0].strip()) if len(row) == 1 else None
        if match:
            rows.extend([[match[1]], [match[2], match[3]]])
        else:
            rows.append(row)
    return rows


def labelled_lines(markdown: str) -> list[tuple[str, str]]:
    return labelled_pairs(invoice_rows(markdown), KNOWN)


def percent(value: str) -> Decimal | None:
    if not re.fullmatch(r"\d+(?:\.\d+)?\s*%", value):
        return None
    number = Decimal(value.rstrip("% "))
    return number if 0 <= number <= 100 else None


def payment_status(value: str) -> bool | None:
    value = value.lower()
    if value in {"paid", "paid in full", "fully paid", "yes", "true"}:
        return True
    if value in {"unpaid", "not paid", "no", "false"}:
        return False
    return None


def classify_document(titles: list) -> str | None:
    # PDF gives precedence between tiers, not within a tier.
    if None in titles:
        return None
    higher = set(titles) & {"tax_invoice", "bill", "invoice"}
    return one(list(higher)) if higher else one(titles)


def document_number(pairs: list[tuple[str, str]], kind: str | None) -> str | None:
    groups = {
        "invoice": {"invoice number", "invoice no", "invoice no.", "invoice #"},
        "receipt": {"receipt number", "receipt no", "receipt no.", "receipt #"},
        "bill": {"bill number"},
        "generic": {"document number"},
        "reference": {"reference number", "reference no", "reference no.", "reference #"},
    }
    # For tax invoices, use an invoice number first and a receipt number if no
    # invoice number exists. Invoice priority is confirmed by the user.
    order = {
        "tax_invoice": ["invoice", "receipt", "generic", "reference"],
        "invoice": ["invoice", "generic", "reference"],
        "receipt": ["receipt", "generic", "reference"],
        "bill": ["bill", "generic", "reference"],
        "customer_copy": ["generic", "reference"],
    }.get(kind, ["generic", "reference"])
    # Keep useful unambiguous explicitly labelled IDs if document type is absent.
    if kind is None:
        order = ["unclassified", "reference"]
        groups["unclassified"] = set().union(*(groups[k] for k in ("invoice", "receipt", "bill", "generic")))
    for group in order:
        matches = [v for k, v in pairs if k in groups[group]]
        if matches:
            normalized = [re.sub(r"\s", "", v) if v and v.lower() not in {"unknown", "n/a", "null"} else None for v in matches]
            return one(normalized)  # Conflicts never fall through to another ID.
    return None


def safe_buyer(value: str) -> str | None:
    # Do not emit explicitly labelled or standalone payment-card identifiers.
    if re.search(r"\b(?:card|visa|mastercard|amex|eftpos)\b", value, re.I):
        return None
    if re.fullmatch(r"[\d\s*Xx#-]+", value):
        digits = re.sub(r"\s", "", value)
        if not re.fullmatch(r"[0-9]{11}", digits):
            return None
    return value


class RuleInvoiceExtractor:
    LABELS = LABELS

    def extract(self, document: str) -> TaxInvoice:
        rows = invoice_rows(document)
        pairs = labelled_pairs(rows, KNOWN)
        # This deployment remains AUD-only although currency is not an output key.
        if re.search(r"\b(?:USD|NZD|EUR|GBP|CAD|JPY|CNY|SGD|HKD)\b|US\$|NZ\$|[€£¥]", document, re.I):
            raise ExtractionError("Unsupported explicit currency")
        for key, value in pairs:
            if key == "currency" and value.upper() != "AUD":
                raise ExtractionError("Unsupported explicit currency")
        values = {}
        titles = [TITLES[label(row[0])] for row in rows if len(row) == 1 and label(row[0]) in TITLES]
        titles += [TITLES.get(label(v)) for k, v in pairs if k == "document type"]
        values["document_type"] = classify_document(titles)
        for field, labels in LABELS.items():
            candidates = [v for k, v in pairs if k in labels]
            if field in {"date_of_issue", "date_of_expense", "payment_due_date"}:
                candidates = [parse_date(v) for v in candidates]
            elif field in {"gst", "total_cost"}:
                candidates = [money(v) for v in candidates]
            elif field == "seller_abn":
                candidates = [re.sub(r"\s", "", v) for v in candidates]
                candidates = [v if re.fullmatch(r"[0-9]{11}", v) else None for v in candidates]
            elif field == "paid":
                candidates = [payment_status(v) for v in candidates]
            elif field in {"supply_type", "expense_category"}:
                allowed = SUPPLY_TYPES if field == "supply_type" else EXPENSE_CATEGORIES
                normalized = [re.sub(r"\s+", "_", v.strip().lower()) for v in candidates]
                candidates = [v if v in allowed else None for v in normalized]
            elif field == "buyer_identity":
                candidates = [safe_buyer(v) if v and v.lower() not in {"unknown", "n/a", "null"} else None for v in candidates]
            elif field == "taxable_sale_extent":
                candidates = [percent(v) for v in candidates]
            else:
                candidates = [v if v and v.lower() not in {"n/a", "null", "unknown"} else None for v in candidates]
            values[field] = one(candidates)
        values["document_number"] = document_number(pairs, values["document_type"])
        values["buyer_identity"] = values["buyer_identity"] or ""
        # Dataset convention supplied in labelling-standards.pdf, not a tax-law
        # conclusion. Use only the exact standalone example; retain conflicts.
        includes_gst = any(len(row) == 1 and row[0].strip().rstrip(".").lower() == "total price includes gst" for row in rows)
        if includes_gst:
            percentages = [percent(v) for k, v in pairs if k in LABELS["taxable_sale_extent"]]
            values["taxable_sale_extent"] = one(percentages + [Decimal("100")])
        total = values["total_cost"]
        values["is_total_cost_equal_to_or_higher_than_1000"] = total >= Decimal("1000") if total is not None else None
        return TaxInvoice(**values)
