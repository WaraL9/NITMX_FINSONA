"""Parser for the Finsona synthetic statement layout (FINSONA-SYNTH-STATEMENT v1).

Column positions are read from each page's table header, not hard-coded, so small
layout shifts don't break it. Money figures are right-aligned, so a money word goes to
the numeric column whose header right edge is nearest; text goes to the rightmost text
column whose header starts at or before it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import pdfplumber

from app.core.dates import parse_thai_date
from app.core.money import to_money
from app.parsers.base import BBox, PageInfo, ParsedRow, ParsedStatement, ParseError, register

MARKER = "FINSONA-SYNTH-STATEMENT v1"

HEADERS = {
    "วันที่": "date",
    "เวลา": "time",
    "รายการ": "code",
    "ถอนเงิน": "debit",
    "ฝากเงิน": "credit",
    "คงเหลือ": "balance",
    "ช่องทาง": "channel",
    "รายละเอียด": "details",
}
NUMERIC = {"debit", "credit", "balance"}

MONEY_RE = re.compile(r"^-?\d{1,3}(,\d{3})*\.\d{2}$")
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")
COUNTERPARTY_RE = re.compile(
    r"^(?:จาก|ไปยัง)\s+(?P<name>.+?)\s+(?P<bank>[A-Z]{2,6})\s+(?P<acct>x{3}-x-x\d{4}-x)(?:\s+.*)?$"
)
INFO_PATTERNS = {
    "bank_code": re.compile(r"ธนาคาร \(Bank\):\s*(\S+)"),
    "account_name": re.compile(r"ชื่อบัญชี \(Account name\):\s*(.+)"),
    "account_no": re.compile(r"เลขที่บัญชี \(Account no\.\):\s*(\S+)"),
    "period": re.compile(r"รอบรายการ \(Period\):\s*(\d{2}/\d{2}/\d{2})\s*-\s*(\d{2}/\d{2}/\d{2})"),
    "opening": re.compile(r"ยอดยกมา \(Opening balance\):\s*([\d,]+\.\d{2})"),
}
MAX_TEXT_SIZE = 12  # anything larger is the watermark or a title
LINE_TOL = 2.0


@dataclass
class _Col:
    key: str
    x0: float
    x1: float


def _columns(words: list[dict]) -> tuple[list[_Col], float] | None:
    """Find the table header on a page; returns columns (left to right) and header bottom."""
    hits = [w for w in words if w["text"] in HEADERS]
    if not hits:
        return None
    # The header is the line containing the most header labels.
    best_top = max({round(w["top"]) for w in hits}, key=lambda t: sum(abs(w["top"] - t) <= LINE_TOL for w in hits))
    line = [w for w in hits if abs(w["top"] - best_top) <= LINE_TOL]
    if len(line) < len(HEADERS):
        return None
    cols = sorted((_Col(HEADERS[w["text"]], w["x0"], w["x1"]) for w in line), key=lambda c: c.x0)
    return cols, max(w["bottom"] for w in line)


def _assign(word: dict, cols: list[_Col]) -> str:
    text = word["text"]
    if MONEY_RE.match(text):
        numeric = [c for c in cols if c.key in NUMERIC]
        return min(numeric, key=lambda c: abs(word["x1"] - c.x1)).key
    text_cols = [c for c in cols if c.key not in NUMERIC and c.x0 <= word["x0"] + 2]
    return text_cols[-1].key if text_cols else cols[0].key


def _group_lines(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= LINE_TOL:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


class SynthV1Parser:
    name = "finsona-synth"
    version = "synth-v1.0"

    def detect(self, first_page_text: str) -> bool:
        return MARKER in first_page_text

    def _header_info(self, text: str) -> dict:
        out: dict = {}
        for key, rx in INFO_PATTERNS.items():
            m = rx.search(text)
            if m:
                out[key] = m.groups() if key == "period" else m.group(1).strip()
        return out

    def parse(self, pdf: pdfplumber.PDF) -> ParsedStatement:
        info = self._header_info(pdf.pages[0].extract_text() or "")
        warnings: list[str] = []
        pages: list[PageInfo] = []
        rows: list[ParsedRow] = []

        for page in pdf.pages:
            pno = page.page_number
            pages.append(PageInfo(pno, float(page.width), float(page.height)))
            words = [
                w for w in page.extract_words(x_tolerance=1.5, y_tolerance=2, extra_attrs=["size"])
                if w["size"] <= MAX_TEXT_SIZE
            ]
            found = _columns(words)
            if not found:
                warnings.append(f"page {pno}: table header not found")
                continue
            cols, header_bottom = found
            table_x0 = cols[0].x0 - 2
            table_x1 = float(page.width) - table_x0
            body = [w for w in words if w["top"] > header_bottom + 1 and w["bottom"] < float(page.height) - 30]

            for line in _group_lines(body):
                cells: dict[str, list[str]] = {}
                for w in line:
                    cells.setdefault(_assign(w, cols), []).append(w["text"])
                date_txt = " ".join(cells.get("date", []))
                if not DATE_RE.match(date_txt):
                    # Continuation of a wrapped details cell.
                    if rows and cells.get("details"):
                        rows[-1].description += " " + " ".join(cells["details"])
                    else:
                        warnings.append(f"page {pno}: skipped unrecognised line {' '.join(w['text'] for w in line)!r}")
                    continue
                time_txt = " ".join(cells.get("time", ["00:00"]))
                if not TIME_RE.match(time_txt):
                    raise ParseError(f"page {pno}: bad time {time_txt!r}")
                if "balance" not in cells:
                    raise ParseError(f"page {pno}: row without balance on {date_txt}")
                d = parse_thai_date(date_txt)
                hh, mm = (int(x) for x in time_txt.split(":"))
                details = " ".join(cells.get("details", []))
                cp = COUNTERPARTY_RE.match(details)
                rows.append(
                    ParsedRow(
                        page_no=pno,
                        row_index=len(rows),
                        posted_at=datetime(d.year, d.month, d.day, hh, mm),
                        code=" ".join(cells.get("code", [])),
                        channel=" ".join(cells.get("channel", [])),
                        description=details,
                        debit=to_money(cells["debit"][0]) if "debit" in cells else to_money(0),
                        credit=to_money(cells["credit"][0]) if "credit" in cells else to_money(0),
                        balance=to_money(cells["balance"][0]),
                        bbox=BBox(
                            x0=table_x0,
                            top=min(w["top"] for w in line) - 2,
                            x1=table_x1,
                            bottom=max(w["bottom"] for w in line) + 2,
                        ),
                        counterparty_name=cp.group("name") if cp else None,
                        counterparty_bank=cp.group("bank") if cp else None,
                        counterparty_account=cp.group("acct") if cp else None,
                    )
                )

        period = info.get("period")
        stmt = ParsedStatement(
            parser=self.name,
            parser_version=self.version,
            bank_code=info.get("bank_code"),
            account_no=info.get("account_no"),
            account_name=info.get("account_name"),
            period_start=parse_thai_date(period[0]) if period else None,
            period_end=parse_thai_date(period[1]) if period else None,
            opening_balance=to_money(info["opening"]) if "opening" in info else None,
            pages=pages,
            rows=rows,
            warnings=warnings,
        )
        breaks = stmt.continuity_breaks()
        if breaks:
            stmt.warnings.append(f"balance continuity broken at {len(breaks)} row(s): {breaks[:10]}")
        return stmt


register(SynthV1Parser())
