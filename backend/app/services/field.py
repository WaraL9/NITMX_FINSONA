"""RM field assistant (E12-01..03, E7-07) and SME portal logic (E13-01, E13-04, E13-05).

Everything here is deterministic: scores, gaps and pre-qualification are formulas over
the case data and the engine's latest analysis, each with a Thai explanation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import ratios
from app.models import Case, CreditMemo, Document, Query, TaxFiling, WatchlistItem
from app.services import consent
from app.services.analysis import DEFAULT_POLICY, latest_analysis

ASSESSMENT_SLA = timedelta(hours=48)


def _months(start, end) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


@dataclass
class Gap:
    kind: str  # data | evidence | structure | risk | consent | opportunity
    title: str
    starter: str  # what the RM can say to the customer
    impact: str | None = None  # THB effect on the safe limit, when quantifiable


@dataclass
class Lead:
    case: Case
    score: int
    group: str  # ready | restructure | needs_data
    reasons: list[str] = field(default_factory=list)
    dscr_at_request: str | None = None
    safe_limit: str | None = None
    open_queries: int = 0


def _sizing(case: Case, result: dict, amount: Decimal) -> ratios.Sizing:
    haircut = Decimal(result.get("alt_data", {}).get("haircut", "0"))
    cfo = Decimal(result["clean_cash_flow_monthly"]) * (1 - haircut)
    return ratios.size(amount, cfo, Decimal(result["existing_debt_monthly"]), case.annual_rate, case.tenor_months,
                       DEFAULT_POLICY)


def score_case(db: Session, case: Case) -> Lead:
    """E12-02: completeness (40) + repayment headroom (40) + revenue verification (20)."""
    reasons: list[str] = []
    docs = db.scalars(select(Document).where(Document.case_id == case.id)).all()
    statements = [d for d in docs if d.kind == "statement"]
    filings = {f.period for f in db.scalars(select(TaxFiling).where(TaxFiling.case_id == case.id))}
    grants = {p: c is not None and c.granted for p, c in consent.current(db, case.id).items()}

    completeness = 15 if statements else 0
    if case.period_start and case.period_end:
        months = _months(case.period_start, case.period_end)
        completeness += round(10 * len(filings & set(months)) / max(len(months), 1))
    completeness += 10 if grants.get("promptbiz_data") else 0
    completeness += 5 if grants.get("utility_data") else 0
    reasons.append(f"ความครบถ้วนของข้อมูล {completeness}/40")

    a = latest_analysis(db, case.id)
    headroom, verification, dscr_s, safe_s = 0, 0, None, None
    group = "needs_data"
    if a is not None:
        r = a.result
        s = _sizing(case, r, case.requested_amount)
        dscr_s, safe_s = (f"{s.dscr:.4f}" if s.dscr is not None else None), f"{s.safe_limit:.2f}"
        if s.meets_target:
            headroom, group = 40, "ready"
        elif s.passes_min:
            headroom, group = 25, "ready"
        elif s.safe_limit >= case.requested_amount * Decimal("0.5"):
            headroom, group = 15, "restructure"
        else:
            headroom = 5
        verified = Decimal(r["waterfall"]["verified_operating_revenue"]) or Decimal(1)
        verification = round(20 * float(Decimal(r["tiers"]["T1_golden"]) / verified))
        reasons.append(f"ความสามารถชำระหนี้ที่วงเงินขอ {headroom}/40 (DSCR {s.dscr:.2f})" if s.dscr else "ยังคำนวณ DSCR ไม่ได้")
        reasons.append(f"สัดส่วนรายได้ยืนยันด้วย PromptBiz {verification}/20")
    else:
        reasons.append("ยังไม่มีผลวิเคราะห์ — ต้องรวบรวมเอกสาร")
    open_q = db.query(Query).filter(Query.case_id == case.id, Query.status == "open").count()
    return Lead(case, completeness + headroom + verification, group, reasons, dscr_s, safe_s, open_q)


def gaps(db: Session, case: Case) -> list[Gap]:
    """E12-03 + E7-07: what is missing, what to say, and what it is worth."""
    out: list[Gap] = []
    grants = {p: c is not None and c.granted for p, c in consent.current(db, case.id).items()}
    for p, label in consent.PURPOSES.items():
        if not grants.get(p):
            out.append(Gap("consent", f"ยังไม่มีความยินยอม: {label}",
                           "รบกวนกดยืนยันความยินยอมในแอป เพื่อให้ธนาคารใช้ข้อมูลนี้ช่วยยืนยันรายได้แทนการขอเอกสารกระดาษ"))
    if case.period_start and case.period_end:
        filed = {f.period for f in db.scalars(select(TaxFiling).where(TaxFiling.case_id == case.id))}
        missing = [m for m in _months(case.period_start, case.period_end) if m not in filed]
        if missing:
            out.append(Gap("data", f"ขาดแบบ ภ.พ.30 {len(missing)} เดือน ({', '.join(missing)})",
                           "ขอแบบ ภ.พ.30 ของเดือนที่ขาด เพื่อยืนยันยอดขายที่ยื่นภาษี (ระดับ 2)"))
    a = latest_analysis(db, case.id)
    if a is None:
        out.append(Gap("data", "ยังไม่มีสเตทเมนต์/ผลวิเคราะห์",
                       "ขอสเตทเมนต์ทุกบัญชีที่ใช้ทำธุรกิจย้อนหลัง 6 เดือน (ไฟล์ PDF จากแอปธนาคารได้เลย)"))
        return out
    r = a.result
    drivers = {d["key"]: d for d in r.get("drivers", [])}
    pending = db.scalars(select(WatchlistItem).where(WatchlistItem.case_id == case.id,
                                                     WatchlistItem.status.in_(("pending", "queried")))).all()
    if pending and "unverified" in drivers:
        out.append(Gap("evidence", f"เงินเข้า {len(pending)} รายการยังไม่มีเอกสารรองรับ",
                       "ถามลูกค้าว่ายอดเงินเหล่านี้คือค่างานอะไร และขอสัญญาจ้าง/ใบส่งของ/ภาพหน้างานประกอบ",
                       f"ศักยภาพเพิ่มวงเงินได้สูงสุด {Decimal(drivers['unverified']['impact']):,.0f} บาท"))
    s = _sizing(case, r, case.requested_amount)
    st = ratios.structure(case.requested_amount, s.safe_limit, Decimal(r.get("t1_monthly", "0")), DEFAULT_POLICY)
    if st.needed:
        out.append(Gap("structure", f"วงเงินที่ขอ {case.requested_amount:,.0f} บาท สูงกว่าที่ผ่อนไหว",
                       f"เสนอวงเงินระยะยาว {st.term_loan:,.0f} บาท + Trade Line {st.trade_line:,.0f} บาท ผูกใบแจ้งหนี้ PromptBiz "
                       "ผ่อนสบายกว่าและไม่เสียประวัติจากการถูกปฏิเสธ",
                       f"รวม {st.total:,.0f} บาท"))
    alt = r.get("alt_data") or {}
    if Decimal(alt.get("haircut", "0")) > 0:
        out.append(Gap("risk", "พบการชำระค่าไฟ/ค่าน้ำ/ค่าเช่าล่าช้า",
                       "สอบถามสาเหตุการชำระค่าสาธารณูปโภคล่าช้า และสภาพคล่องช่วงนั้น",
                       f"ตอนนี้ถูกปรับลดกระแสเงินสด {Decimal(alt['haircut']) * 100:.0f}%"))
    verified = Decimal(r["waterfall"]["verified_operating_revenue"]) or Decimal(1)
    share = Decimal(r["tiers"]["T1_golden"]) / verified
    if share < Decimal("0.6"):
        out.append(Gap("opportunity", f"รายได้ที่ยืนยันด้วย PromptBiz เพียง {share * 100:.0f}%",
                       "ชวนลูกค้าออกใบแจ้งหนี้ให้ลูกค้ารายใหญ่ผ่าน PromptBiz — ยืนยันรายได้อัตโนมัติ และเปิดวงเงิน Trade Line"))
    return out


# ---------------- SME pre-qualification (E13-01/02) ----------------

# Indicative operating-cash-flow margins by industry (assumption table; a bank would calibrate).
INDUSTRY_MARGINS = {
    "contractor": ("รับเหมาก่อสร้าง/ตกแต่ง", Decimal("0.14")),
    "manufacturing": ("โรงงาน/การผลิต", Decimal("0.12")),
    "retail": ("ค้าปลีก/ค้าส่ง", Decimal("0.08")),
    "food": ("ร้านอาหาร/เครื่องดื่ม", Decimal("0.10")),
    "services": ("บริการ", Decimal("0.18")),
    "agriculture": ("เกษตร/แปรรูปสินค้าเกษตร", Decimal("0.09")),
}


@dataclass
class PreQual:
    result: str  # high | conditional | mismatch
    indicative_cfo: Decimal
    dscr: Decimal | None
    safe_limit: Decimal
    reasons: list[str]
    unlocks: list[str]


def prequalify(amount: Decimal, industry: str, monthly_revenue: Decimal, existing_debt: Decimal, rate: Decimal,
               tenor: int) -> PreQual:
    label, margin = INDUSTRY_MARGINS[industry]
    cfo = (monthly_revenue * margin).quantize(Decimal("0.01"))
    s = ratios.size(amount, cfo, existing_debt, rate, tenor, DEFAULT_POLICY)
    reasons = [f"ประมาณกระแสเงินสดจากยอดขาย × อัตรากำไรเงินสดเฉลี่ยของธุรกิจ{label} ({margin * 100:.0f}%) = {cfo:,.0f} บาท/เดือน"]
    unlocks = ["เชื่อมข้อมูลใบแจ้งหนี้ PromptBiz เพื่อยืนยันรายได้อัตโนมัติ (ระดับ 1)",
               "ส่งแบบ ภ.พ.30 ย้อนหลัง 6 เดือน เพื่อยืนยันยอดขายที่ยื่นภาษี"]
    if s.meets_target:
        result = "high"
        reasons.append(f"ผ่อนไหวสบาย: DSCR ประมาณ {s.dscr:.2f} เท่า")
    elif s.passes_min:
        result = "conditional"
        reasons.append(f"ผ่านเกณฑ์ขั้นต่ำ (DSCR ประมาณ {s.dscr:.2f}) แต่ต้องยืนยันรายได้ด้วยข้อมูลจริง")
    else:
        result = "mismatch"
        reasons.append(f"วงเงินที่ขอสูงกว่าที่ผ่อนไหว (DSCR ประมาณ {s.dscr:.2f})" if s.dscr else "ยังไม่มีกระแสเงินสดรองรับหนี้ใหม่")
        if s.safe_limit > 0:
            reasons.append(f"วงเงินที่มีโอกาสผ่านมากที่สุดประมาณ {s.safe_limit:,.0f} บาท — ไม่ใช่การปฏิเสธ แต่เป็นขนาดที่ปลอดภัยกว่า")
    return PreQual(result, cfo, s.dscr, s.safe_limit, reasons, unlocks)


# ---------------- SME tracker (E13-05) ----------------

STAGES = [
    ("documents", "ตรวจสอบความครบถ้วนของเอกสาร"),
    ("analysis", "จัดระเบียบกระแสเงินสดและจับคู่ข้อมูลการค้าดิจิทัล"),
    ("review", "เจ้าหน้าที่วิเคราะห์สินเชื่อตรวจสอบเชิงลึก"),
    ("committee", "เสนอคณะกรรมการสินเชื่อ"),
    ("contract", "อนุมัติและนัดหมายลงนามสัญญา"),
]


def tracker(db: Session, case: Case) -> dict:
    has_docs = db.query(Document).filter(Document.case_id == case.id, Document.kind == "statement").count() > 0
    analysed = latest_analysis(db, case.id) is not None
    memo = db.scalar(select(CreditMemo).where(CreditMemo.case_id == case.id))
    signed = memo is not None and memo.status == "signed"
    done = [has_docs and case.submitted_at is not None, analysed, signed, signed, False]
    current = next((i for i, d in enumerate(done) if not d), len(STAGES) - 1)
    due = (case.submitted_at + ASSESSMENT_SLA) if case.submitted_at else None
    now = datetime.now(timezone.utc)
    if due is not None and due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return {
        "stages": [{"key": k, "label": label, "status": "done" if done[i] else ("current" if i == current else "todo")}
                   for i, (k, label) in enumerate(STAGES)],
        "sla_due": due.isoformat() if due else None,
        "sla_hours_left": round((due - now).total_seconds() / 3600, 1) if due else None,
        "outcome": {"recommendation": memo.recommendation,
                    "approved_amount": f"{memo.approved_amount:.2f}" if memo.approved_amount is not None else None,
                    "trade_line_amount": f"{memo.trade_line_amount:.2f}" if memo.trade_line_amount is not None else None}
        if signed else None,
    }
