"""Synthetic utility & rent payment history (E1-05) for the utility sandbox connector.

12 months of electricity, water and rent bills. Months covered by the bank statements
reuse the exact amounts and dates of the matching statement debits, so the alternative
data and the statements agree. Two scenarios:
  clean                    all paid before the due date (the canonical demo case)
  late_electricity_twice   Mar and Apr 2026 electricity paid 35-45 days late (what-if)
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from app.core.money import to_money
from app.synth.generator import GeneratedCase

SCENARIOS = ("clean", "late_electricity_twice")
LATE_PERIODS = {"2026-03": 38, "2026-04": 44}


def _months_back(end: date, n: int) -> list[tuple[int, int]]:
    y, m, out = end.year, end.month, []
    for _ in range(n):
        out.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(out))


def make_alt_data(gen: GeneratedCase, seed: int = 21) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    end = gen.scenario.case.period_end
    stmt = {}
    for t in gen.accounts["BBL_CUR"].rows:
        key = None
        if "ค่าไฟฟ้า" in t.details:
            key = "electricity"
        elif "ค่าน้ำประปา" in t.details:
            key = "water"
        elif "ค่าเช่า" in t.details:
            key = "rent"
        if key:
            stmt[(key, t.at.strftime("%Y-%m"))] = (t.at.date(), t.debit)

    base: list[dict] = []
    for y, m in _months_back(end, 12):
        period = f"{y:04d}-{m:02d}"
        for kind, due_day, lo, hi in (("electricity", 25, 15000, 28000), ("water", 27, 2000, 4000),
                                      ("rent", 5, 85000, 85000)):
            due = date(y, m, due_day)
            if (kind, period) in stmt:
                paid, amount = stmt[(kind, period)]
            else:
                amount = to_money(round(rng.uniform(lo, hi), 2)) if lo != hi else to_money(lo)
                paid = due - timedelta(days=rng.randint(1, 6))
            base.append({"kind": kind, "period": period, "due_date": due.isoformat(),
                         "paid_date": paid.isoformat(), "amount": f"{Decimal(amount):.2f}"})

    late = []
    for b in base:
        b2 = dict(b)
        if b["kind"] == "electricity" and b["period"] in LATE_PERIODS:
            due = date.fromisoformat(b["due_date"])
            b2["paid_date"] = (due + timedelta(days=LATE_PERIODS[b["period"]])).isoformat()
        late.append(b2)
    return {"clean": base, "late_electricity_twice": late}
