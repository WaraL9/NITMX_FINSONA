"""Render a synthetic account statement to PDF (E1-02).

The layout mimics a typical Thai bank statement (landscape table: date, time, code,
withdrawal, deposit, balance, channel, details), but every page is clearly marked as a
synthetic demo document so it can never pass as a real bank record.

Returns the ground-truth row bands (page, top, bottom in PDF points, top-left origin) so
tests can check that the parser's bounding boxes land on the right rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from app.config import settings
from app.core.money import fmt_thb
from app.synth.generator import GeneratedAccount

FORMAT_MARKER = "FINSONA-SYNTH-STATEMENT v1"

PAGE_W, PAGE_H = landscape(A4)
MX = 28  # horizontal margin
ROW_H = 13.0
TABLE_TOP = 168.0  # top of first data row (top-left coords)
TABLE_BOTTOM = PAGE_H - 44
ROWS_PER_PAGE = int((TABLE_BOTTOM - TABLE_TOP) // ROW_H)
BODY = 8.0

# (label, anchor x, alignment). Numeric columns are right-aligned on their anchor.
COLUMNS = [
    ("วันที่", MX + 2, "left"),
    ("เวลา", 78, "left"),
    ("รายการ", 110, "left"),
    ("ถอนเงิน", 300, "right"),
    ("ฝากเงิน", 385, "right"),
    ("คงเหลือ", 475, "right"),
    ("ช่องทาง", 487, "left"),
    ("รายละเอียด", 545, "left"),
]
DETAILS_MAX_W = PAGE_W - MX - 545

ACCOUNT_TYPE_TH = {"current": "กระแสรายวัน", "savings": "ออมทรัพย์"}

_fonts_ready = False


def _ensure_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return
    fonts = settings.data_dir / "fonts"
    pdfmetrics.registerFont(TTFont("Sarabun", str(fonts / "Sarabun-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Sarabun-SemiBold", str(fonts / "Sarabun-SemiBold.ttf")))
    _fonts_ready = True


def be_date(d: date) -> str:
    """dd/mm/yy in the Buddhist era, as Thai statements print it."""
    return f"{d.day:02d}/{d.month:02d}/{(d.year + 543) % 100:02d}"


def _fit(text: str, font: str, size: float, max_w: float) -> str:
    if pdfmetrics.stringWidth(text, font, size) <= max_w:
        return text
    while text and pdfmetrics.stringWidth(text + "…", font, size) > max_w:
        text = text[:-1]
    return text + "…"


@dataclass
class RowBand:
    page: int  # 1-based
    top: float
    bottom: float


def render_statement(acct: GeneratedAccount, period: tuple[date, date], out: Path,
                     password: str | None = None) -> list[RowBand]:
    _ensure_fonts()
    out.parent.mkdir(parents=True, exist_ok=True)
    enc = StandardEncryption(password, canPrint=1, strength=128) if password else None
    c = Canvas(str(out), pagesize=(PAGE_W, PAGE_H), encrypt=enc, invariant=1)
    c.setTitle(f"Synthetic statement {acct.spec.bank_code} {acct.spec.account_no_masked}")
    c.setAuthor("Finsona AI synthetic data generator")

    rows = acct.rows
    pages = max(1, -(-len(rows) // ROWS_PER_PAGE))
    bands: list[RowBand] = []

    def y(top: float, size: float = BODY) -> float:
        """Top-left 'top of text line' -> ReportLab baseline."""
        return PAGE_H - top - size * 0.95

    for p in range(pages):
        # Watermark first so it sits behind the table.
        c.saveState()
        c.setFillGray(0.93)
        c.setFont("Sarabun-SemiBold", 64)
        c.translate(PAGE_W / 2, PAGE_H / 2)
        c.rotate(24)
        c.drawCentredString(0, 0, "SYNTHETIC · ตัวอย่างสังเคราะห์")
        c.restoreState()

        c.setFillGray(0.45)
        c.setFont("Sarabun", 7)
        c.drawString(MX, y(16, 7), "เอกสารสังเคราะห์เพื่อการสาธิตระบบ Finsona AI — ไม่ใช่รายการเดินบัญชีจริงของธนาคารใด "
                                   "(Synthetic demo document, not a real bank record)")
        c.drawRightString(PAGE_W - MX, y(16, 7), FORMAT_MARKER)

        c.setFillGray(0.1)
        c.setFont("Sarabun-SemiBold", 13)
        c.drawString(MX, y(34, 13), "รายการเคลื่อนไหวบัญชี (Statement of Account)")
        c.setFont("Sarabun-SemiBold", 11)
        c.drawRightString(PAGE_W - MX, y(34, 11), f"{acct.spec.bank_code} · Synthetic")

        info = [
            f"ธนาคาร (Bank): {acct.spec.bank_code}",
            f"ชื่อบัญชี (Account name): {acct.spec.account_name}",
            f"เลขที่บัญชี (Account no.): {acct.spec.account_no_masked}",
            f"ประเภทบัญชี (Type): {ACCOUNT_TYPE_TH.get(acct.spec.account_type, acct.spec.account_type)}",
            f"รอบรายการ (Period): {be_date(period[0])} - {be_date(period[1])}",
            f"ยอดยกมา (Opening balance): {fmt_thb(acct.opening_balance)}",
        ]
        c.setFont("Sarabun", 8.5)
        for i, line in enumerate(info):
            c.drawString(MX, y(58 + i * 12, 8.5), line)

        # Table header
        hdr_top = TABLE_TOP - 17
        c.setFillGray(0.9)
        c.rect(MX, PAGE_H - hdr_top - 15, PAGE_W - 2 * MX, 15, stroke=0, fill=1)
        c.setFillGray(0.1)
        c.setFont("Sarabun-SemiBold", BODY)
        for label, x, align in COLUMNS:
            (c.drawRightString if align == "right" else c.drawString)(x, y(hdr_top + 3), label)

        # Rows
        chunk = rows[p * ROWS_PER_PAGE:(p + 1) * ROWS_PER_PAGE]
        for i, t in enumerate(chunk):
            top = TABLE_TOP + i * ROW_H
            if i % 2:
                c.setFillGray(0.965)
                c.rect(MX, PAGE_H - top - ROW_H, PAGE_W - 2 * MX, ROW_H, stroke=0, fill=1)
            c.setFillGray(0.1)
            c.setFont("Sarabun", BODY)
            ty = y(top + 2.2)
            c.drawString(COLUMNS[0][1], ty, be_date(t.at.date()))
            c.drawString(COLUMNS[1][1], ty, t.at.strftime("%H:%M"))
            c.drawString(COLUMNS[2][1], ty, t.code)
            if t.debit:
                c.drawRightString(COLUMNS[3][1], ty, fmt_thb(t.debit))
            if t.credit:
                c.drawRightString(COLUMNS[4][1], ty, fmt_thb(t.credit))
            c.drawRightString(COLUMNS[5][1], ty, fmt_thb(t.balance or Decimal(0)))
            c.drawString(COLUMNS[6][1], ty, t.channel)
            c.drawString(COLUMNS[7][1], ty, _fit(t.details, "Sarabun", BODY, DETAILS_MAX_W))
            bands.append(RowBand(p + 1, top, top + ROW_H))

        c.setFillGray(0.45)
        c.setFont("Sarabun", 7)
        c.drawRightString(PAGE_W - MX, 24, f"หน้า {p + 1} / {pages}")
        c.drawString(MX, 24, f"{acct.spec.bank_code} {acct.spec.account_no_masked}")
        c.showPage()

    c.save()
    return bands
