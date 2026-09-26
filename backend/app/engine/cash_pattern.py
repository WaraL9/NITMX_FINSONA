"""Cash-withdrawal pattern detector (E4-06).

Cash-intensive SMEs (contractors, recyclers, rice mills) withdraw cash on a fixed rhythm
to pay site labour and buy materials from suppliers who only take cash. Generic scoring
treats that as leakage. This detector shows when the withdrawals follow an operating
rhythm, so the analyst (and the memo) can treat them as genuine operating cost.

Deterministic: weekday concentration, regularity and size. The LLM may later phrase the
explanation, but these facts are the evidence.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from app.engine.types import ETxn

WEEKDAYS_TH = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
MIN_COUNT = 12  # about two a month over six months
CONCENTRATION = 0.8  # share of withdrawals on the top two weekdays


@dataclass
class CashPattern:
    detected: bool
    count: int
    total: Decimal
    average: Decimal
    top_weekdays: list[str]
    weekday_share: float
    morning_share: float
    txn_ids: list[int]


def detect(withdrawals: list[ETxn]) -> CashPattern:
    n = len(withdrawals)
    total = sum((t.debit for t in withdrawals), Decimal("0.00"))
    if n == 0:
        return CashPattern(False, 0, total, Decimal("0.00"), [], 0.0, 0.0, [])
    days = Counter(t.posted_at.weekday() for t in withdrawals)
    top = [d for d, _ in days.most_common(2)]
    share = sum(days[d] for d in top) / n
    morning = sum(1 for t in withdrawals if t.posted_at.hour < 11) / n
    return CashPattern(
        detected=n >= MIN_COUNT and share >= CONCENTRATION,
        count=n,
        total=total,
        average=(total / n).quantize(Decimal("0.01")),
        top_weekdays=[WEEKDAYS_TH[d] for d in sorted(top)],
        weekday_share=round(share, 3),
        morning_share=round(morning, 3),
        txn_ids=[t.id for t in withdrawals],
    )
