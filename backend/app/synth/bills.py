"""Synthetic utility & rent bills (E2-14) for the SME to upload.

Built from the statement's own utility and rent debits, so an uploaded bill can be
matched to the bank payment that settled it. Written per case to `bills/`:
  * `bill_electricity_<period>.pdf`   e-bill PDF with a text layer, paid via the statement
  * `bill_water_<period>.jpg`         phone photo (stored sideways + EXIF rotation flag) with a
                                      recorded OCR response; the amount is smudged, so a CA
                                      has to confirm it (E2-09 gating)
  * `receipt_rent_<period>.pdf`       landlord receipt: printed paid date and lease end date
Not ingested by the seed — the canonical figures only move if someone uploads one.
"""

from __future__ import annotations

import hashlib
import io
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from app.core.money import fmt_thb
from app.ocr.images import IMAGE_DPI
from app.parsers.bill import text_layer_words
from app.synth.generator import GeneratedCase
from app.synth.statement_pdf import _ensure_fonts

PROVIDERS = {"electricity": "การไฟฟ้านครหลวง", "water": "การประปานครหลวง"}
TITLES = {"electricity": "ใบแจ้งค่าไฟฟ้า", "water": "ใบแจ้งค่าน้ำประปา", "rent": "ใบเสร็จรับเงิน ค่าเช่า"}
PHOTO_SCALE = 2.0  # rendered px per PDF point
PHOTO_MARGIN = 70  # px of table around the paper


@dataclass
class SynthBill:
    kind: str
    period: str  # YYYY-MM
    provider: str
    customer_name: str
    customer_no: str
    due_date: date
    amount: Decimal
    paid_date: date | None = None  # printed on receipts only
    lease_end: date | None = None


def _be(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}/{d.year + 543}"


def render_bill(b: SynthBill) -> bytes:
    _ensure_fonts()
    w, h = A4
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A4, invariant=1)
    c.setTitle(f"Synthetic {b.kind} bill {b.period}")

    def at(top: float) -> float:
        return h - top

    c.saveState()
    c.setFillGray(0.93)
    c.setFont("Sarabun-SemiBold", 54)
    c.translate(w / 2, h / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, "SYNTHETIC · ตัวอย่าง")
    c.restoreState()

    c.setFillGray(0.45)
    c.setFont("Sarabun", 7)
    c.drawString(40, at(28), "เอกสารสังเคราะห์เพื่อการสาธิตระบบ Finsona AI — ไม่ใช่เอกสารจริง")
    c.setFillGray(0.1)
    c.setFont("Sarabun-SemiBold", 16)
    c.drawString(40, at(62), TITLES[b.kind])
    c.setFont("Sarabun", 11)
    y, m = int(b.period[:4]), int(b.period[5:])
    lines = [f"ผู้ให้บริการ: {b.provider}",
             f"{'ผู้เช่า' if b.kind == 'rent' else 'ชื่อผู้ใช้บริการ'}: {b.customer_name}",
             f"{'เลขที่สัญญาเช่า' if b.kind == 'rent' else 'หมายเลขผู้ใช้บริการ'}: {b.customer_no}",
             f"{'ค่าเช่าเดือน' if b.kind == 'rent' else 'ประจำเดือน'}: {m:02d}/{y + 543}",
             f"กำหนดชำระ: {_be(b.due_date)}"]
    if b.paid_date:
        lines.append(f"ชำระเมื่อ: {_be(b.paid_date)}")
    if b.lease_end:
        lines.append(f"สัญญาเช่าสิ้นสุด: {_be(b.lease_end)}")
    top = 100
    for s in lines:
        c.drawString(40, at(top), s)
        top += 22
    top += 10
    c.setStrokeGray(0.8)
    c.line(40, at(top - 14), w - 40, at(top - 14))
    c.setFont("Sarabun-SemiBold", 13)
    label = "จำนวนเงินที่ชำระ" if b.paid_date else "จำนวนเงินที่ต้องชำระ"
    c.drawString(40, at(top + 6), f"{label}: {fmt_thb(b.amount)} บาท")
    c.showPage()
    c.save()
    return buf.getvalue()


def photograph(pdf: bytes, out: Path, recordings: Path, seed: int, smudge: tuple[str, ...] = ()) -> str:
    """Write a phone photo of the bill (JPEG, sideways + EXIF orientation 6) and the OCR
    response a layout model would return for it. `smudge` lists label prefixes whose value
    reads correctly but with low confidence. Returns the photo's SHA-256."""
    rng = random.Random(seed)
    doc = pdfium.PdfDocument(pdf)
    paper = doc[0].render(scale=PHOTO_SCALE).to_pil().convert("RGB")
    doc.close()
    img = Image.new("RGB", (paper.width + 2 * PHOTO_MARGIN, paper.height + 2 * PHOTO_MARGIN), (96, 84, 72))
    img.paste(paper, (PHOTO_MARGIN, PHOTO_MARGIN))
    px = img.load()
    for _ in range(img.width * img.height // 500):
        x, y = rng.randrange(img.width), rng.randrange(img.height)
        px[x, y] = (rng.randint(60, 200),) * 3
    img = img.filter(ImageFilter.GaussianBlur(0.8))

    # OCR words in the page coordinates ingest will use (upright image at IMAGE_DPI).
    k = 72 / IMAGE_DPI
    words = []
    for line_words in _by_line(text_layer_words(pdf)[0].words):
        label = " ".join(w["text"] for w in line_words)
        low = any(label.startswith(p) for p in smudge)
        for w in line_words:
            has_digit = any(ch.isdigit() for ch in w["text"])
            conf = rng.uniform(0.38, 0.47) if low and has_digit else rng.uniform(0.93, 0.995)
            words.append({"text": w["text"],
                          "x0": round((PHOTO_MARGIN + w["x0"] * PHOTO_SCALE) * k, 2),
                          "top": round((PHOTO_MARGIN + w["top"] * PHOTO_SCALE) * k, 2),
                          "x1": round((PHOTO_MARGIN + w["x1"] * PHOTO_SCALE) * k, 2),
                          "bottom": round((PHOTO_MARGIN + w["bottom"] * PHOTO_SCALE) * k, 2),
                          "size": round((w["bottom"] - w["top"]) * PHOTO_SCALE * k, 2),
                          "confidence": round(conf, 3)})

    # Phones keep the sensor orientation and flag the rotation in EXIF.
    stored = img.transpose(Image.Transpose.ROTATE_90)
    exif = Image.Exif()
    exif[0x0112] = 6
    jpg = io.BytesIO()
    stored.save(jpg, "JPEG", quality=70, exif=exif.tobytes())
    data = jpg.getvalue()
    out.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    recordings.mkdir(parents=True, exist_ok=True)
    (recordings / f"{sha}.json").write_text(json.dumps({
        "provider": "recorded-layout", "model": "prebuilt-layout", "source": out.name,
        "pages": [{"page_no": 1, "width": round(img.width * k, 2), "height": round(img.height * k, 2),
                   "words": words}],
        "truth": [],
    }, ensure_ascii=False), encoding="utf-8")
    return sha


def _by_line(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= 3:
            lines[-1].append(w)
        else:
            lines.append([w])
    return lines


def make_bills(gen: GeneratedCase) -> list[tuple[SynthBill, dict]]:
    """Latest electricity bill, the month before's water bill, and the latest rent receipt,
    each for an amount the statement actually paid. Returns (bill, statement payment)."""
    sc = gen.scenario.case
    debits = sorted((t for t in gen.accounts["BBL_CUR"].rows if t.debit > 0), key=lambda t: t.at)

    def last(keyword: str, before_month: int = 0):
        hits = [t for t in debits if keyword in t.details]
        return hits[-1 - before_month]

    elec, water, rent = last("ค่าไฟฟ้า"), last("ค่าน้ำประปา", 1), last("ค่าเช่า")

    def ref(t) -> dict:
        return {"posted_at": t.at.isoformat(), "amount": f"{t.debit:.2f}"}

    def cust_no(t) -> str:
        return t.details.split()[-1]

    maturity = sc.period_end + timedelta(days=round(gen.scenario.loan_request.tenor_months * 30.44))
    return [
        (SynthBill("electricity", f"{elec.at:%Y-%m}", PROVIDERS["electricity"], sc.company_name, cust_no(elec),
                   date(elec.at.year, elec.at.month, 25), elec.debit), ref(elec)),
        (SynthBill("water", f"{water.at:%Y-%m}", PROVIDERS["water"], sc.company_name, cust_no(water),
                   date(water.at.year, water.at.month, 27), water.debit), ref(water)),
        (SynthBill("rent", f"{rent.at:%Y-%m}", rent.counterparty or "ผู้ให้เช่า", sc.company_name, "L-2023-0412",
                   date(rent.at.year, rent.at.month, 5), rent.debit, paid_date=rent.at.date(),
                   # The lease runs out a few months before the loan would be repaid (E6-06 tenor signal).
                   lease_end=date(maturity.year, maturity.month, 1) - timedelta(days=62)), ref(rent)),
    ]


def write_bills(gen: GeneratedCase, out_dir: Path, recordings: Path, seed: int = 5) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for i, (b, paid_by) in enumerate(make_bills(gen)):
        pdf = render_bill(b)
        if b.kind == "water":
            name = f"bill_water_{b.period}.jpg"
            photograph(pdf, out_dir / name, recordings, seed + i, smudge=("จำนวนเงิน",))
        else:
            name = f"{'receipt' if b.paid_date else 'bill'}_{b.kind}_{b.period}.pdf"
            (out_dir / name).write_bytes(pdf)
        written.append({"file": name, "kind": b.kind, "period": b.period, "due_date": b.due_date.isoformat(),
                        "amount": f"{b.amount:.2f}", "customer_no": b.customer_no,
                        "paid_date": b.paid_date.isoformat() if b.paid_date else None,
                        "lease_end": b.lease_end.isoformat() if b.lease_end else None,
                        "statement_payment": paid_by, "photo": name.endswith(".jpg")})
    return written
