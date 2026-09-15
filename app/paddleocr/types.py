from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.core.errors import ParserError


@dataclass
class ParsedDocument:
    raw_pages: list[dict]
    markdown_pages: list[str]
    versions: dict[str, str] = field(default_factory=dict)


class DocumentParser(Protocol):
    def parse(self, path: Path) -> ParsedDocument: ...


class PartialParseError(ParserError):
    def __init__(self, message: str, raw_pages: list[dict], diagnostic: dict | None = None):
        super().__init__(message)
        self.raw_pages = raw_pages
        self.diagnostic = diagnostic or {}
