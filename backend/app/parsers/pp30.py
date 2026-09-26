"""ภ.พ.30 (VAT return) parser (E2-12).

Reads the tax ID, tax month and the numbered amount lines, and keeps each amount's
bounding box so a declared-sales figure can be traced back to the form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

import pdfplumber

from app.core.dates import normalize_year
from app.core.money import to_money
from app.parsers.base import BBox, ParseError

MARKER = "FINSONA-SYNTH-PP30 v1"

MONEY_RE = re.compile(r"^\d{1,3}(,\d{3})*\.\d{2}$")
TAX_ID_RE = re.compile(r"เลขประจำตัวผู้เสียภาษีอากร:\s*(\d{13})")
MONTH_RE = re.compile(r"เดือนภาษี:\s*(\d{1,2})/(\d{4})")
# Line number on the official form -> field name
LINES = {"1.": "sales", "5.": "output_vat", "6.": "purchases", "7.": "input_vat", "8.": "vat_payable"}


@dataclass
class ParsedPP30:
    parser: str
    parser_version: str
    tax_id: str
    period: str  # YYYY-MM (CE)
    amounts: dict[str, Decimal]
    bboxes: dict[str, BBox]
    page_width: float
    page_height: float
    warnings: list[str] = field(default_factory=list)


def detect_pp30(first_page_text: str) -> bool:
    return MARKER in first_page_text


def parse_pp30(pdf_path_or_file) -> ParsedPP30:
    with pdfplumber.open(pdf_path_or_file) as pdf:
        page = pdf.pages[0]
        text = page.extract_text() or ""
        if not detect_pp30(text):
            raise ParseError("not a recognised ภ.พ.30 layout")
        tax = TAX_ID_RE.search(text)
        month = MONTH_RE.search(text)
        if not tax or not month:
            raise ParseError("ภ.พ.30 is missing the tax ID or tax month")
        words = [w for w in page.extract_words(x_tolerance=1.5, extra_attrs=["size"]) if w["size"] <= 14]

        lines: list[list[dict]] = []
        for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
            if lines and abs(lines[-1][0]["top"] - w["top"]) <= 2:
                lines[-1].append(w)
            else:
                lines.append([w])

        amounts: dict[str, Decimal] = {}
        bboxes: dict[str, BBox] = {}
        for line in lines:
            line.sort(key=lambda w: w["x0"])
            key = LINES.get(line[0]["text"])
            money = [w for w in line if MONEY_RE.match(w["text"])]
            if key and money:
                v = money[-1]
                amounts[key] = to_money(v["text"])
                bboxes[key] = BBox(line[0]["x0"] - 2, min(w["top"] for w in line) - 2, v["x1"] + 2,
                                   max(w["bottom"] for w in line) + 2)

        missing = [k for k in LINES.values() if k not in amounts]
        if "sales" in missing:
            raise ParseError("ภ.พ.30 sales line (1.) not found")
        warnings = [f"missing line: {k}" for k in missing]
        if not missing and amounts["output_vat"] - amounts["input_vat"] != amounts["vat_payable"]:
            warnings.append("line 8 does not equal line 5 - line 7")
        m, y = int(month.group(1)), normalize_year(int(month.group(2)))
        return ParsedPP30(
            parser="finsona-synth-pp30",
            parser_version="pp30-v1.0",
            tax_id=tax.group(1),
            period=f"{y:04d}-{m:02d}",
            amounts=amounts,
            bboxes=bboxes,
            page_width=float(page.width),
            page_height=float(page.height),
            warnings=warnings,
        )
