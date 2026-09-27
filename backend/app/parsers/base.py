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
    """No registered parser recognises this document."""


class NoTextLayer(UnsupportedFormat):
    """Image-only PDF (a scan or photo): route to OCR (E2-08)."""


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
    confidence: float = 1.0  # min over the key fields; 1.0 for a digital text layer
    field_confidence: dict[str, float] = field(default_factory=dict)  # OCR only (E2-09)
    counterparty_name: str | None = None
    counterparty_bank: str | None = None
    counterparty_account: str | None = None


@dataclass
class PageInfo:
    page_no: int
    width: float
    height: float


@dataclass
class PageWords:
    """One page as positioned words — from a PDF text layer or an OCR provider (E2-08).

    Each word: text, x0, top, x1, bottom (PDF points, top-left origin), size (font size or
    glyph height) and, from OCR, confidence in [0, 1].
    """

    page_no: int
    width: float
    height: float
    words: list[dict]


def page_text(words: list[dict], tol: float = 2.0) -> str:
    """Rebuild reading-order text from positioned words (for format detection on OCR output)."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return "\n".join(" ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"])) for line in lines)


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
    duplicate_pages: list[int] = field(default_factory=list)  # E2-11: skipped, same content as an earlier page

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

    def parse_words(self, first_page_text: str, pages: list[PageWords]) -> ParsedStatement: ...


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
            raise NoTextLayer("no text layer (scanned image?) — needs OCR")
        for p in _REGISTRY:
            if p.detect(first):
                return p.parse(pdf)
    raise UnsupportedFormat("statement layout not recognised by any parser")


def parse_statement_words(pages: list[PageWords]) -> ParsedStatement:
    """Parse OCR output with the same layout parsers as digital PDFs (E2-08)."""
    from app.parsers import synth_v1  # noqa: F401

    if not pages:
        raise ParseError("OCR returned no pages")
    first = page_text(pages[0].words)
    for p in _REGISTRY:
        if p.detect(first):
            return p.parse_words(first, pages)
    raise UnsupportedFormat("statement layout not recognised in the OCR text")
