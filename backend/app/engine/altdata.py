"""Alternative data: utility and rent payment behaviour (E6-06).

Rules from ITMX.md (Alternative Data Risk Matrix), over the last 6 months of bills:
  * all paid on time over 12 months     -> business liveness confirmed, haircut 0%
  * 1 bill paid > 30 days late           -> cash-flow haircut 5%
  * 2+ bills paid > 30 days late         -> haircut 10%
  * any bill > 60 days late or unpaid    -> haircut 25% + Early Warning Signal (EWS)
Missed utility/rent payments typically precede a bank default by 30-90 days, so the
haircut is applied to the cash flow used for sizing, not to reported revenue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from app.core.i18n import th

KIND_TH = {"electricity": th("ค่าไฟฟ้า"), "water": th("ค่าน้ำประปา"), "rent": th("ค่าเช่า")}


@dataclass(frozen=True)
class EBill:
    kind: str
    period: str  # YYYY-MM
    due_date: date
    paid_date: date | None
    amount: Decimal


@dataclass
class AltDataResult:
    months_covered: int
    bills: int
    on_time: int
    late_30: int
    late_60_or_unpaid: int
    haircut: Decimal  # 0.00 .. 0.25
    ews: bool
    liveness_confirmed: bool
    signals: list[str] = field(default_factory=list)


def days_late(b: EBill, as_of: date) -> int:
    paid = b.paid_date or as_of
    return max(0, (paid - b.due_date).days)


def evaluate(bills: list[EBill], as_of: date) -> AltDataResult:
    if not bills:
        return AltDataResult(0, 0, 0, 0, 0, Decimal("0"), False, False, [th("ไม่มีข้อมูลการชำระค่าสาธารณูปโภค/ค่าเช่า")])
    periods = sorted({b.period for b in bills})
    recent_periods = set(periods[-6:])
    recent = [b for b in bills if b.period in recent_periods]
    late30 = [b for b in recent if 30 < days_late(b, as_of) <= 60]
    late60 = [b for b in recent if days_late(b, as_of) > 60 or (b.paid_date is None and b.due_date < as_of)]
    late60 = [b for b in late60 if b not in late30] if late60 else []
    on_time = sum(1 for b in bills if days_late(b, as_of) == 0)

    signals: list[str] = []
    if late60:
        haircut, ews = Decimal("0.25"), True
        signals += [th(f"{KIND_TH.get(b.kind, b.kind)} งวด {b.period} ค้างชำระเกิน 60 วัน") for b in late60]
    elif len(late30) >= 2:
        haircut, ews = Decimal("0.10"), False
    elif len(late30) == 1:
        haircut, ews = Decimal("0.05"), False
    else:
        haircut, ews = Decimal("0"), False
    signals += [th(f"{KIND_TH.get(b.kind, b.kind)} งวด {b.period} ชำระล่าช้า {days_late(b, as_of)} วัน") for b in late30]
    liveness = len(periods) >= 12 and on_time == len(bills)
    if liveness:
        signals.insert(0, th(f"ชำระค่าสาธารณูปโภคและค่าเช่าตรงเวลาครบ {len(periods)} เดือน — ยืนยันการเปิดดำเนินกิจการต่อเนื่อง"))
    return AltDataResult(len(periods), len(bills), on_time, len(late30), len(late60), haircut, ews, liveness, signals)
