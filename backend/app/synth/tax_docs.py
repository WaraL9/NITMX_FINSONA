"""Synthetic PromptBiz e-invoices (E1-03) and ภ.พ.30 filings (E1-04).

Invoices: one per T1 receipt, issued 7-45 days before payment. About a quarter are paid
net of 3% withholding tax (WHT on the pre-VAT amount), so payment < invoice total, as in
real B2B practice. A few invoices are still unpaid at the end of the period.

ภ.พ.30: per month, declared sales + output VAT = T1 + T2 receipts in that month plus a
small slack (sales invoiced but not yet collected). The slack is always far below the
smallest Watchlist amount, so unverified inflows can never hide inside declared sales.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from app.core.money import fmt_thb, to_money
from app.synth.generator import REVENUE_T1, REVENUE_T2, GeneratedCase
from app.synth.statement_pdf import _ensure_fonts, be_date

VAT = Decimal("0.07")
WHT = Decimal("0.03")
PP30_MARKER = "FINSONA-SYNTH-PP30 v1"


@dataclass
class SynthInvoice:
    invoice_no: str
    issue_date: date
    seller_tax_id: str
    buyer_name: str
    buyer_tax_id: str
    subtotal: Decimal
    vat: Decimal
    total: Decimal
    wht: Decimal
    paid_amount: Decimal | None
    paid_at: datetime | None
    settlement_ref: str | None

    def to_json(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = f"{v:.2f}"
            elif isinstance(v, (date, datetime)):
                d[k] = v.isoformat()
        return d


@dataclass
class SynthPP30:
    tax_id: str
    year: int
    month: int
    sales: Decimal  # excl. VAT
    output_vat: Decimal
    purchases: Decimal  # excl. VAT
    input_vat: Decimal

    @property
    def vat_payable(self) -> Decimal:
        return self.output_vat - self.input_vat

    @property
    def period(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def _q(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def make_invoices(gen: GeneratedCase, seed: int = 7) -> list[SynthInvoice]:
    rng = random.Random(seed)
    tax_id = gen.scenario.case.tax_id
    buyers: dict[str, str] = {}
    receipts = sorted(
        (t for a in gen.accounts.values() for t in a.rows if t.category == REVENUE_T1), key=lambda t: t.at
    )
    out: list[SynthInvoice] = []
    for i, t in enumerate(receipts, 1):
        buyer_tax = buyers.setdefault(t.counterparty, f"0105{rng.randint(10**8, 10**9 - 1)}")
        if rng.random() < 0.25:
            # paid = total - WHT, WHT = 3% of subtotal, total = subtotal * 1.07
            subtotal = _q(t.credit / (1 + VAT - WHT))
            wht = _q(subtotal * WHT)
        else:
            subtotal = _q(t.credit / (1 + VAT))
            wht = Decimal("0.00")
        vat = _q(subtotal * VAT)
        issue = t.at.date() - timedelta(days=rng.randint(7, 45))
        out.append(SynthInvoice(
            invoice_no=f"INV-{issue:%y%m}-{i:04d}",
            issue_date=issue,
            seller_tax_id=tax_id,
            buyer_name=t.counterparty,
            buyer_tax_id=buyer_tax,
            subtotal=subtotal,
            vat=vat,
            total=subtotal + vat,
            wht=wht,
            paid_amount=t.credit,
            paid_at=t.at,
            settlement_ref=f"PBZ{t.at:%y%m%d}{rng.randint(100000, 999999)}",
        ))
    # A few invoices still outstanding at period end (no matching receipt).
    end = gen.scenario.case.period_end
    names = sorted(buyers)
    for j in range(4):
        subtotal = to_money(rng.randint(50, 300) * 1000)
        name = names[j % len(names)]
        issue = end - timedelta(days=rng.randint(2, 20))
        out.append(SynthInvoice(
            invoice_no=f"INV-{issue:%y%m}-{len(out) + 1:04d}", issue_date=issue, seller_tax_id=tax_id,
            buyer_name=name, buyer_tax_id=buyers[name], subtotal=subtotal, vat=_q(subtotal * VAT),
            total=subtotal + _q(subtotal * VAT), wht=Decimal("0.00"), paid_amount=None, paid_at=None,
            settlement_ref=None,
        ))
    return out


def make_pp30(gen: GeneratedCase, seed: int = 11) -> list[SynthPP30]:
    rng = random.Random(seed)
    sc = gen.scenario
    filings = []
    y, m = sc.case.period_start.year, sc.case.period_start.month
    while (y, m) <= (sc.case.period_end.year, sc.case.period_end.month):
        receipts = sum(
            (t.credit for a in gen.accounts.values() for t in a.rows
             if t.category in (REVENUE_T1, REVENUE_T2) and (t.at.year, t.at.month) == (y, m)),
            Decimal("0.00"),
        )
        declared_incl_vat = receipts + to_money(rng.randint(5, 30) * 1000)  # slack << 450,000
        sales = _q(declared_incl_vat / (1 + VAT))
        output_vat = declared_incl_vat - sales
        purchases = _q(sales * Decimal(str(rng.uniform(0.55, 0.7))))
        filings.append(SynthPP30(sc.case.tax_id, y, m, sales, output_vat, purchases, _q(purchases * VAT)))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return filings


def render_pp30(f: SynthPP30, company_name: str, out: Path) -> dict[str, list[float]]:
    """One-page synthetic ภ.พ.30. Returns field bands (top-left coords) for lineage tests."""
    _ensure_fonts()
    out.parent.mkdir(parents=True, exist_ok=True)
    w, h = A4
    c = Canvas(str(out), pagesize=A4, invariant=1)
    c.setTitle(f"Synthetic PP30 {f.period}")

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
    c.drawString(40, at(28), "เอกสารสังเคราะห์เพื่อการสาธิตระบบ Finsona AI — ไม่ใช่แบบแสดงรายการภาษีจริง")
    c.drawRightString(w - 40, at(28), PP30_MARKER)
    c.setFillGray(0.1)
    c.setFont("Sarabun-SemiBold", 15)
    c.drawString(40, at(58), "แบบ ภ.พ.30 แบบแสดงรายการภาษีมูลค่าเพิ่ม")
    c.setFont("Sarabun", 10)
    lines = [
        f"ชื่อผู้ประกอบการ: {company_name}",
        f"เลขประจำตัวผู้เสียภาษีอากร: {f.tax_id}",
        f"เดือนภาษี: {f.month:02d}/{f.year + 543}",
    ]
    for i, s in enumerate(lines):
        c.drawString(40, at(90 + i * 16), s)

    fields = [
        ("sales", "1. ยอดขายในเดือนนี้", f.sales),
        ("output_vat", "5. ภาษีขายเดือนนี้", f.output_vat),
        ("purchases", "6. ยอดซื้อที่มีสิทธินำภาษีซื้อมาหักในการคำนวณภาษีเดือนนี้", f.purchases),
        ("input_vat", "7. ภาษีซื้อเดือนนี้", f.input_vat),
        ("vat_payable", "8. ภาษีที่ต้องชำระเดือนนี้", f.vat_payable),
    ]
    bands: dict[str, list[float]] = {}
    top = 160
    for key, label, value in fields:
        c.setStrokeGray(0.85)
        c.line(40, at(top + 18), w - 40, at(top + 18))
        c.drawString(40, at(top + 12), label)
        c.drawRightString(w - 40, at(top + 12), fmt_thb(value))
        bands[key] = [top, top + 18]
        top += 26
    c.setFont("Sarabun", 8)
    c.setFillGray(0.45)
    c.drawString(40, at(top + 20), f"ยื่นแบบวันที่ {be_date(date(f.year, f.month, 1) + timedelta(days=45))}")
    c.showPage()
    c.save()
    return bands
