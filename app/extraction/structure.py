"""Read conservative label/value structure, without executing HTML or guessing layout."""
from html import unescape
from html.parser import HTMLParser
import re


def clean(text: str) -> str:
    text = re.sub(r"^\s*#+\s*", "", unescape(text))
    return re.sub(r"\s+", " ", re.sub(r"[*`]", "", text)).strip()


def label(text: str) -> str:
    return clean(text).rstrip(":：").strip().lower().replace("_", " ")


class DocumentRows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.prose = ""
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.table_depth = 0
        self.complex_row = False
        self.ignored = 0

    def flush(self):
        for line in self.prose.splitlines():
            if line.strip():
                cells = [clean(v) for v in line.strip().strip("|").split("|")]
                if all(re.fullmatch(r":?-{3,}:?", v) for v in cells):
                    continue
                self.rows.append(cells)
            else:
                self.rows.append([])  # Never pair across blank paragraphs.
        self.prose = ""

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored += 1
        if self.ignored:
            return
        if tag == "table":
            self.flush()
            self.rows.append([])
            self.table_depth += 1
        elif tag == "tr":
            self.row = []
            self.complex_row = self.table_depth > 1
        elif tag in {"td", "th"}:
            self.cell = []
            if any(k in {"rowspan", "colspan"} and v != "1" for k, v in attrs):
                self.complex_row = True
        elif tag == "br":
            if self.cell is not None:
                self.cell.append("\n")
            else:
                self.prose += "\n"
        elif tag in {"p", "div", "h1", "h2", "h3"} and not self.table_depth:
            self.prose += "\n"

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.ignored = max(0, self.ignored - 1)
            return
        if self.ignored:
            return
        if tag in {"td", "th"}:
            if self.row is not None and self.cell is not None:
                self.row.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr":
            self.rows.append(self.row if self.row is not None and not self.complex_row else [])
            self.row = None
        elif tag == "table":
            self.table_depth = max(0, self.table_depth - 1)
            self.rows.append([])
        elif tag in {"p", "div", "h1", "h2", "h3"} and not self.table_depth:
            self.prose += "\n"

    def handle_data(self, data):
        if self.ignored:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif not self.table_depth:
            self.prose += data


def document_rows(markdown: str) -> list[list[str]]:
    parser = DocumentRows()
    parser.feed(markdown)
    parser.close()
    parser.flush()
    return parser.rows


def labelled_pairs(rows: list[list[str]], known: set[str]) -> list[tuple[str, str]]:
    pairs = []
    customer_section = False
    buyer_labels = {"customer", "bill to", "buyer", "recipient", "buyer identity", "buyer name", "customer name"}
    seller_labels = {"supplier", "seller", "business name", "supplier name", "seller business name", "seller name"}

    def emit(key, value):
        nonlocal customer_section
        key = label(key)
        if key in buyer_labels:
            customer_section = True
        elif key in seller_labels and key != "business name":
            customer_section = False
        if key == "abn" and customer_section:
            key = "buyer abn"
        if key in {"business name", "name"} and customer_section:
            key = "buyer name"
        pairs.append((key, clean(value)))

    i = 0
    ordered = sorted(known, key=len, reverse=True)
    while i < len(rows):
        cells = rows[i]
        if not cells:
            i += 1
            continue
        keys = [label(c) for c in cells]
        # Horizontal header followed by exactly one value per column.
        if len(cells) > 1 and all(k in known for k in keys):
            if i + 1 < len(rows) and len(rows[i + 1]) == len(cells):
                values = rows[i + 1]
                if not any(label(v) in known for v in values):
                    for k, v in zip(keys, values):
                        emit(k, v)
                    i += 2
                    continue
            i += 1
            continue
        # Vertical key/value rows, including multiple adjacent pairs.
        if len(cells) > 1 and len(cells) % 2 == 0 and all(keys[j] in known for j in range(0, len(keys), 2)):
            for j in range(0, len(cells), 2):
                emit(cells[j], cells[j + 1])
            i += 1
            continue
        for cell in cells:
            lines = [clean(v) for v in cell.splitlines() if clean(v)]
            if len(lines) == 2 and label(lines[0]) in known and label(lines[1]) not in known:
                emit(lines[0], lines[1])
                continue
            text = clean(cell)
            key = label(text)
            if key in known:
                if key in buyer_labels:
                    customer_section = True
                elif key in seller_labels and key != "business name":
                    customer_section = False
                if len(cells) == 1 and i + 1 < len(rows) and len(rows[i + 1]) == 1:
                    value = rows[i + 1][0]
                    # Do not consume another label, title or labelled field.
                    if label(value) not in known and not re.search(r"[:：]", value) and not value.lstrip().startswith("#") and not any(clean(value).lower().startswith(k + " ") for k in known):
                        emit(key, value)
                        i += 1
                continue
            split = re.split(r"[:：]", text, maxsplit=1)
            if len(split) == 2:
                emit(split[0], split[1])
                continue
            # Explicit known labels may be separated from values by whitespace.
            for candidate in ordered:
                if text.lower().startswith(candidate + " "):
                    emit(candidate, text[len(candidate):].strip())
                    break
        i += 1
    return pairs
