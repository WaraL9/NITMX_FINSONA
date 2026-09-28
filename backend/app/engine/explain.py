"""Decision attribution (E7-06): why the safe limit is what it is.

Each factor's impact is measured by ablation: recompute the safe limit with that factor
removed, and report the difference in THB. Deterministic and reproducible; nothing is
estimated by a model. Impacts are one-at-a-time, so they don't sum to the total (the
safe limit is floored at zero and rounded), and the UI says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.engine.ratios import limit_at
from app.engine.types import Policy
from app.core.i18n import th

ZERO = Decimal("0")


@dataclass
class Driver:
    kind: str  # positive | risk | info
    key: str
    title: str
    detail: str
    impact: Decimal  # THB change in safe limit attributable to the factor (signed)
    metric: str | None = None  # lineage metric behind the factor


@dataclass
class ExplainInputs:
    months: int
    cfo_monthly: Decimal  # after any alt-data haircut
    cfo_monthly_before_haircut: Decimal
    existing_debt_monthly: Decimal
    annual_rate: Decimal
    tenor_months: int
    requested: Decimal
    tiers: dict[str, Decimal]  # period totals
    household: Decimal  # period total
    pending_unverified: Decimal  # period total
    loops: Decimal
    owner_inflow: Decimal
    haircut: Decimal
    cash_pattern_detected: bool
    cash_total: Decimal
    policy: Policy


def _fmt(d: Decimal) -> str:
    return f"{d:,.0f}"


def explain(x: ExplainInputs) -> tuple[Decimal, list[Driver]]:
    p, r, n = x.policy, x.annual_rate, x.tenor_months

    def safe(cfo: Decimal, existing: Decimal | None = None) -> Decimal:
        return limit_at(cfo, x.existing_debt_monthly if existing is None else existing, p.target_dscr, r, n)

    base = safe(x.cfo_monthly)
    per_month = lambda v: v / x.months  # noqa: E731
    drivers: list[Driver] = []

    tier_titles = {
        "T1_golden": (th("รายได้ยืนยันด้วยใบแจ้งหนี้ PromptBiz / e-Tax"),
                      th("ยอดรับชำระตรงกับ e-Invoice บนโครงข่าย PromptBiz หรือใบกำกับภาษีอิเล็กทรอนิกส์")),
        "T2_tax": (th("รายได้สอดคล้องกับ ภ.พ.30"), th("อยู่ในยอดขายที่ยื่นกรมสรรพากร")),
        "T3_operational": (th("รายได้เชิงบริบท (พร้อมเพย์/ลูกค้าประจำ/CA รับรอง)"), th("มีหลักฐานการค้าต่อเนื่อง")),
    }
    for key, (title, why) in tier_titles.items():
        amount = x.tiers.get(key, ZERO)
        if amount > 0:
            drivers.append(Driver("positive", key, title,
                                  th(f"{why} รวม {_fmt(amount)} บาท — หากไม่นับ วงเงินปลอดภัยจะลดลง"),
                                  base - safe(x.cfo_monthly - per_month(amount)), key))

    if x.household > 0:
        drivers.append(Driver("positive", "household", th("แยกค่าใช้จ่ายครัวเรือนออกจากต้นทุนธุรกิจ"),
                              th(f"ค่าเทอม ค่างวดรถส่วนตัว และเงินโอนให้ครอบครัว {_fmt(x.household)} บาท "
                              "ไม่ถูกนับเป็นต้นทุนของบริษัท (Commingling Filter)"),
                              base - safe(x.cfo_monthly - per_month(x.household)), "household"))

    if x.cash_pattern_detected:
        drivers.append(Driver("info", "cash_pattern", th("การถอนเงินสดเป็นรอบสม่ำเสมอ"),
                              th(f"ถอนเงินสดรวม {_fmt(x.cash_total)} บาท เป็นรอบวันซื้อวัสดุ/จ่ายค่าแรงหน้างาน — "
                              "นับเป็นต้นทุนดำเนินงานจริง ไม่ใช่เงินรั่วไหล"), ZERO, "cost_cash_withdrawal"))

    if x.loops > 0 or x.owner_inflow > 0:
        drivers.append(Driver("info", "netting", th("ตัดยอดหมุนเวียนเทียมและเงินทุนเจ้าของออกแล้ว"),
                              th(f"เงินโอนวน {_fmt(x.loops)} บาท และเงินจากเจ้าของ/ครอบครัว {_fmt(x.owner_inflow)} บาท "
                              "ไม่ถูกนับเป็นรายได้ — ป้องกันการประเมินวงเงินเกินจริง"), ZERO, "own_account_loops"))

    if x.existing_debt_monthly > 0:
        drivers.append(Driver("risk", "existing_debt", th("ภาระหนี้เดิม"),
                              th(f"ผ่อนหนี้เดิม {_fmt(x.existing_debt_monthly)} บาท/เดือน ลดความสามารถรับหนี้ใหม่"),
                              base - safe(x.cfo_monthly, ZERO), "debt_service_total"))

    if x.haircut > 0:
        drivers.append(Driver("risk", "alt_data", th("พฤติกรรมชำระค่าสาธารณูปโภค/ค่าเช่า"),
                              th(f"ปรับลดกระแสเงินสด {x.haircut * 100:.0f}% ตามสัญญาณเตือนล่วงหน้า"),
                              base - safe(x.cfo_monthly_before_haircut), None))

    if x.pending_unverified > 0:
        drivers.append(Driver("risk", "unverified", th("รายการรอตรวจสอบ (Watchlist) ยังไม่นับเป็นรายได้"),
                              th(f"เงินเข้า {_fmt(x.pending_unverified)} บาท ยังไม่มีเอกสารรองรับ — "
                              "หาก CA รับรองทั้งหมด วงเงินปลอดภัยจะเพิ่มได้สูงสุดตามตัวเลขนี้"),
                              safe(x.cfo_monthly + per_month(x.pending_unverified)) - base, "unverified_pending"))

    order = {"positive": 0, "risk": 1, "info": 2}
    drivers.sort(key=lambda d: (order[d.kind], -abs(d.impact)))
    return base, drivers
