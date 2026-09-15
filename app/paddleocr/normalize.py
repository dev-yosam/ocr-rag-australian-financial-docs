from app.core.errors import ParserError


def normalize_markdown(pages: list[str]) -> str:
    if not pages or not any(page.strip() for page in pages):
        raise ParserError("Parser returned no readable content")
    normalized = []
    for page in pages:
        # Preserve internal whitespace, table columns, indentation, hard breaks.
        text = page.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\u00a0", " ").replace("\u202f", " ")
        normalized.append(text.strip("\n"))
    return "\n\n<!-- page break -->\n\n".join(normalized) + "\n"
