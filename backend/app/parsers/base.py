"""Statement parser contract and registry (E2-04, E2-05).

Every parser turns a (decrypted) PDF into the same normalized ParsedStatement, where each
row carries its page and bounding box so any number can be traced back to the document.
Bounding boxes are PDF points with a top-left origin (pdfplumber convention).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

import pdfplumber


class ParseError(ValueError):
    """The document looked like a supported format but could not be read."""


class UnsupportedFormat(ParseError):
    """No registered parser recognises this document (routes to OCR later, E2-08)."""


@dataclass
class BBox:
    x0: float
    top: float
    x1: float
    bottom: float


@dataclass
class ParsedRow:
    page_no: int  # 1-based
    row_index: int  # 0-based within the statement
    posted_at: datetime
    code: str
    channel: str
    description: str
    debit: Decimal
    credit: Decimal
    balance: Decimal
    bbox: BBox
    confidence: float = 1.0
    counterparty_name: str | None = None
    counterparty_bank: str | None = None
    counterparty_account: str | None = None


@dataclass
class PageInfo:
    page_no: int
    width: float
    height: float


@dataclass
class ParsedStatement:
    parser: str
    parser_version: str
    bank_code: str | None
    account_no: str | None
    account_name: str | None
    period_start: date | None
    period_end: date | None
    opening_balance: Decimal | None
    pages: list[PageInfo]
    rows: list[ParsedRow]
    warnings: list[str] = field(default_factory=list)

    @property
    def total_debit(self) -> Decimal:
        return sum((r.debit for r in self.rows), Decimal("0.00"))

    @property
    def total_credit(self) -> Decimal:
        return sum((r.credit for r in self.rows), Decimal("0.00"))

    def continuity_breaks(self) -> list[int]:
        """Row indexes where previous balance - debit + credit != printed balance (E2-11)."""
        breaks = []
        prev = self.opening_balance
        for r in self.rows:
            if prev is not None and prev - r.debit + r.credit != r.balance:
                breaks.append(r.row_index)
            prev = r.balance
        return breaks


class StatementParser(Protocol):
    name: str
    version: str

    def detect(self, first_page_text: str) -> bool: ...

    def parse(self, pdf: pdfplumber.PDF) -> ParsedStatement: ...


_REGISTRY: list[StatementParser] = []


def register(parser: StatementParser) -> StatementParser:
    _REGISTRY.append(parser)
    return parser


def parse_statement(pdf_path_or_file) -> ParsedStatement:
    """Detect the format from page 1 and parse. Raises UnsupportedFormat if nothing matches."""
    from app.parsers import synth_v1  # noqa: F401  (registers built-in parsers)

    with pdfplumber.open(pdf_path_or_file) as pdf:
        if not pdf.pages:
            raise ParseError("PDF has no pages")
        first = pdf.pages[0].extract_text() or ""
        if not first.strip():
            raise UnsupportedFormat("no text layer (scanned image?) — OCR path not available yet")
        for p in _REGISTRY:
            if p.detect(first):
                return p.parse(pdf)
    raise UnsupportedFormat("statement layout not recognised by any parser")
