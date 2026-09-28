"""Utility & rent bill parser (E2-14).

Works on positioned words, so the same code reads a bill's PDF text layer and the OCR of
a scan or phone photo (E2-08). It extracts what the alt-data rules need — kind, period,
due date, amount, and the paid date when the document is a receipt — plus the customer
number that also appears on the bank debit, and a lease end date on rent documents.
Each key field keeps its box on the page and, from OCR, its confidence.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pdfplumber

from app.core.dates import normalize_year, parse_thai_date
from app.core.money import MoneyError, to_money
from app.parsers.base import BBox, PageWords, ParseError, UnsupportedFormat
from app.core.i18n import th

PARSER_VERSION = "bill-v1.0"

KINDS = (  # first match wins; rent before utilities (a lease can mention electricity)
    ("rent", re.compile(r"ค่าเช่า")),
    ("electricity", re.compile(r"ค่าไฟฟ้า|การไฟฟ้า")),
    ("water", re.compile(r"ค่าน้ำประปา|การประปา")),
)
TITLE_RE = re.compile(r"ใบแจ้งค่า|ใบแจ้งหนี้|ใบเสร็จรับเงิน")
DATE = r"(\d{1,2}/\d{1,2}/\d{2,4})"
FIELDS = {
    "provider": re.compile(r"^ผู้ให้บริการ\s*:\s*(.+)$"),
    "customer_name": re.compile(r"^(?:ชื่อผู้ใช้บริการ|ผู้เช่า)\s*:\s*(.+)$"),
    "customer_no": re.compile(r"^(?:หมายเลขผู้ใช้บริการ|เลขที่สัญญาเช่า)\s*:\s*(\S+)"),
    "period": re.compile(r"^(?:ประจำเดือน|ค่าเช่าเดือน)\s*:\s*(\d{1,2})/(\d{4})"),
    "due_date": re.compile(rf"^กำหนดชำระ\s*:\s*{DATE}"),
    "paid_date": re.compile(rf"^ชำระเมื่อ\s*:\s*{DATE}"),
    "lease_end": re.compile(rf"^สัญญาเช่าสิ้นสุด\s*:\s*{DATE}"),
    "amount": re.compile(r"^จำนวนเงิน(?:ที่ต้องชำระ|ที่ชำระ|รวม)\s*:?\s*([\d,]+\.\d{2})"),
}
KEY_FIELDS = ("amount", "due_date", "paid_date")  # the ones the late-payment rules read


@dataclass
class ParsedBill:
    parser: str
    parser_version: str
    kind: str  # electricity | water | rent
    is_receipt: bool
    provider: str | None
    customer_name: str | None
    customer_no: str | None
    period: str  # YYYY-MM
    due_date: date
    amount: Decimal
    paid_date: date | None
    lease_end: date | None
    page_width: float
    page_height: float
    bboxes: dict[str, BBox] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)  # key field -> OCR confidence
    warnings: list[str] = field(default_factory=list)


def detect_bill(text: str) -> bool:
    return bool(TITLE_RE.search(text)) and any(p.search(text) for _, p in KINDS) and (
        "กำหนดชำระ" in text or "ชำระเมื่อ" in text)


def text_layer_words(plain: bytes) -> list[PageWords]:
    with pdfplumber.open(io.BytesIO(plain)) as pdf:
        return [PageWords(p.page_number, float(p.width), float(p.height),
                          [w for w in p.extract_words(x_tolerance=1.5, extra_attrs=["size", "upright"])
                           if w["upright"] and w["size"] <= 20])
                for p in pdf.pages[:1]]


def page_text(pages: list[PageWords]) -> str:
    return "\n".join(" ".join(w["text"] for w in line) for p in pages[:1] for line in _lines(p.words))


def _lines(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= 3:
            lines[-1].append(w)
        else:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w["x0"])
    return lines


def _date(text: str, name: str) -> date:
    try:
        return parse_thai_date(text)
    except ValueError as e:
        raise ParseError(f"{name}: unreadable date {text!r}") from e


def parse_bill_words(pages: list[PageWords]) -> ParsedBill:
    if not pages or not pages[0].words:
        raise UnsupportedFormat("no text on the bill")
    page = pages[0]
    lines = _lines(page.words)
    text = "\n".join(" ".join(w["text"] for w in line) for line in lines)
    if not detect_bill(text):
        raise UnsupportedFormat("not a recognised utility or rent bill")
    kind = next(k for k, p in KINDS if p.search(text))

    found: dict[str, re.Match] = {}
    boxes: dict[str, BBox] = {}
    confidence: dict[str, float] = {}
    for line in lines:
        s = " ".join(w["text"] for w in line)
        for name, pattern in FIELDS.items():
            if name in found:
                continue
            m = pattern.match(s)
            if not m:
                continue
            found[name] = m
            boxes[name] = BBox(line[0]["x0"] - 2, min(w["top"] for w in line) - 2, line[-1]["x1"] + 2,
                               max(w["bottom"] for w in line) + 2)
            # The value is the last word(s) of the line; its confidence is the weakest of them.
            value_words = [w for w in line if any(ch.isdigit() for ch in w["text"])] or line
            confs = [w["confidence"] for w in value_words if "confidence" in w]
            if confs:
                confidence[name] = round(min(confs), 3)

    for required in ("period", "due_date", "amount"):
        if required not in found:
            raise ParseError(f"bill field not found: {required}")
    try:
        amount = to_money(found["amount"].group(1))
    except MoneyError as e:
        raise ParseError(f"bill amount unreadable: {found['amount'].group(1)!r}") from e
    m, y = int(found["period"].group(1)), normalize_year(int(found["period"].group(2)))
    if not 1 <= m <= 12:
        raise ParseError(f"bill period month {m} is invalid")
    due = _date(found["due_date"].group(1), "due date")
    paid = _date(found["paid_date"].group(1), "paid date") if "paid_date" in found else None
    lease_end = _date(found["lease_end"].group(1), "lease end") if "lease_end" in found else None

    warnings = []
    if amount <= 0:
        warnings.append(th("ยอดเงินไม่เป็นบวก"))
    if paid and paid > due:
        warnings.append(th(f"ชำระหลังกำหนด {(paid - due).days} วัน"))
    is_receipt = "ใบเสร็จรับเงิน" in text
    if is_receipt and paid is None:
        warnings.append(th("ใบเสร็จไม่มีวันที่ชำระ"))

    def value(name: str) -> str | None:
        return found[name].group(1).strip() if name in found else None

    return ParsedBill(
        parser="finsona-bill", parser_version=PARSER_VERSION, kind=kind, is_receipt=is_receipt,
        provider=value("provider"), customer_name=value("customer_name"), customer_no=value("customer_no"),
        period=f"{y:04d}-{m:02d}", due_date=due, amount=amount, paid_date=paid, lease_end=lease_end,
        page_width=page.width, page_height=page.height,
        bboxes={k: v for k, v in boxes.items() if k in KEY_FIELDS or k == "lease_end"},
        confidence={k: v for k, v in confidence.items() if k in KEY_FIELDS}, warnings=warnings,
    )
