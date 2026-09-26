"""Anomaly flags (E4-09). Pure and deterministic; informational — they never change a figure.

Patterns a credit analyst would want pointed out, each with the rows behind it:

  * pass_through  — money in and (almost) the same amount straight back out to someone
                    else within 48 h: revenue that may only be passing through.
  * period_end    — unexplained or owner money landing in the last days of the period,
                    the classic way to dress up a statement before applying.
  * revenue_spike — a month whose verified revenue is far above the others.
  * round_cash    — repeated large, round cash deposits (cash structuring / unrecorded sales).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from statistics import median

PASS_MIN = Decimal("100000")
PASS_TOL = Decimal("0.005")
PASS_WINDOW = timedelta(hours=48)
PERIOD_END_DAYS = 5
PERIOD_END_SHARE = Decimal("0.20")  # of a month's verified revenue
SPIKE_RATIO = Decimal("1.6")
ROUND_CASH_MIN = Decimal("100000")
ROUND_STEP = Decimal("10000")
REVENUE_TIERS = {"T1_golden", "T2_tax", "T3_operational"}
NOT_THIRD_PARTY = {"own_transfer_loop", "own_transfer_internal", "debt_service"}


@dataclass(frozen=True)
class ATxn:
    id: int
    at: datetime
    debit: Decimal
    credit: Decimal
    tag: str | None
    tier: str | None
    counterparty: str | None
    company: bool  # on a company account


@dataclass
class Anomaly:
    kind: str
    severity: str  # info | watch | high
    title: str
    detail: str
    amount: Decimal
    txn_ids: list[int] = field(default_factory=list)


def _thb(v: Decimal) -> str:
    return f"{v:,.0f}"


def _pass_through(txns: list[ATxn]) -> list[Anomaly]:
    credits = sorted((t for t in txns if t.company and t.credit >= PASS_MIN and t.tag not in NOT_THIRD_PARTY), key=lambda t: t.at)
    debits = sorted((t for t in txns if t.company and t.debit > 0 and t.tag not in NOT_THIRD_PARTY), key=lambda t: t.at)
    used: set[int] = set()
    out: list[Anomaly] = []
    for c in credits:
        for d in debits:
            if d.at < c.at:
                continue
            if d.at - c.at > PASS_WINDOW:
                break
            # Passed on: at most what came in, less a small fee. Paying out MORE than
            # arrived is ordinary spending that happens to be a similar size.
            if d.id in used or d.debit > c.credit or c.credit - d.debit > c.credit * PASS_TOL:
                continue
            if c.counterparty and d.counterparty and c.counterparty == d.counterparty:
                continue  # a refund to the same party is not a pass-through
            used.add(d.id)
            hours = int((d.at - c.at).total_seconds() // 3600)
            out.append(Anomaly(
                "pass_through", "watch", "เงินเข้าแล้วออกทันที",
                f"รับ {_thb(c.credit)} บาท จาก {c.counterparty or 'ไม่ระบุ'} แล้วโอนออก {_thb(d.debit)} บาท "
                f"ให้ {d.counterparty or 'ไม่ระบุ'} ภายใน {hours} ชม. — อาจเป็นเงินผ่านทาง ไม่ใช่รายได้จริง",
                c.credit, [c.id, d.id]))
            break
    return out


def _monthly_revenue(txns: list[ATxn]) -> dict[tuple[int, int], Decimal]:
    months: dict[tuple[int, int], Decimal] = {}
    for t in txns:
        if t.company and t.tier in REVENUE_TIERS:
            k = (t.at.year, t.at.month)
            months[k] = months.get(k, Decimal("0")) + t.credit
    return months


def _period_end(txns: list[ATxn], period_end: date, monthly_avg: Decimal) -> list[Anomaly]:
    start = datetime.combine(period_end - timedelta(days=PERIOD_END_DAYS - 1), datetime.min.time())
    late = [t for t in txns if t.company and t.credit > 0 and t.at >= start
            and (t.tag == "owner_injection" or t.tier == "T4_unverified" or t.tag == "other_income")]
    total = sum((t.credit for t in late), Decimal("0"))
    if not late or monthly_avg <= 0 or total < monthly_avg * PERIOD_END_SHARE:
        return []
    return [Anomaly(
        "period_end", "watch", "เงินไม่ทราบที่มาเข้าช่วงท้ายรอบบัญชี",
        f"{len(late)} รายการรวม {_thb(total)} บาท ใน {PERIOD_END_DAYS} วันสุดท้ายของรอบ "
        f"({total / monthly_avg:.0%} ของรายได้เฉลี่ยต่อเดือน) เป็นเงินเจ้าของหรือยังไม่ยืนยันที่มา — ตรวจว่าเป็นการแต่งยอดก่อนยื่นกู้หรือไม่",
        total, [t.id for t in late])]


def _spikes(txns: list[ATxn]) -> list[Anomaly]:
    months = _monthly_revenue(txns)
    if len(months) < 3:
        return []
    med = Decimal(str(median(months.values())))
    out = []
    for (y, m), v in sorted(months.items()):
        if med > 0 and v > med * SPIKE_RATIO:
            ids = [t.id for t in txns if t.company and t.tier in REVENUE_TIERS and (t.at.year, t.at.month) == (y, m)]
            out.append(Anomaly(
                "revenue_spike", "info", f"รายได้เดือน {m:02d}/{y + 543} สูงผิดปกติ",
                f"{_thb(v)} บาท = {v / med:.1f} เท่าของค่ามัธยฐานรายเดือน ({_thb(med)} บาท) — ตรวจว่าเป็นรายได้ตามฤดูกาลหรือครั้งเดียว",
                v, ids))
    return out


def _round_cash(txns: list[ATxn]) -> list[Anomaly]:
    hits = [t for t in txns if t.company and t.tag == "cash_deposit" and t.credit >= ROUND_CASH_MIN
            and t.credit % ROUND_STEP == 0]
    if len(hits) < 2:
        return []
    total = sum((t.credit for t in hits), Decimal("0"))
    return [Anomaly(
        "round_cash", "watch", "ฝากเงินสดก้อนใหญ่ตัวเลขกลม",
        f"ฝากเงินสด {len(hits)} ครั้ง รวม {_thb(total)} บาท เป็นจำนวนเต็มหมื่นทุกครั้ง — ขอหลักฐานที่มา (ใบเสร็จขาย/บันทึกเงินสด)",
        total, [t.id for t in hits])]


def detect(txns: list[ATxn], period_end: date, months: int) -> list[Anomaly]:
    monthly = _monthly_revenue(txns)
    avg = (sum(monthly.values(), Decimal("0")) / months) if months else Decimal("0")
    found = _pass_through(txns) + _period_end(txns, period_end, avg) + _spikes(txns) + _round_cash(txns)
    order = {"high": 0, "watch": 1, "info": 2}
    return sorted(found, key=lambda a: (order[a.severity], -a.amount))
