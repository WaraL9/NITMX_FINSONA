"""Customer concentration (E5-06). Pure and deterministic.

Who the verified revenue comes from. A business whose top customer pays a third of its
revenue has a single point of failure the cash-flow figures alone do not show.

Customer identity, best evidence first: the PromptBiz invoice buyer for a matched
receipt, otherwise the counterparty name as printed on the statement (normalised, so
"บจก. ABC" and "บริษัท ABC จำกัด" are one customer). Receipts without a named payer
(cash deposits, masked PromptPay senders) are reported as unidentified and left out of
the ranking rather than lumped into one fake "customer".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.engine.rules import normalize_party
from app.core.i18n import th

TOP1_HIGH = Decimal("0.30")  # one customer > 30% of identified revenue
TOP5_HIGH = Decimal("0.70")
HHI_HIGH = 2500  # US DoJ "highly concentrated" on a 0-10,000 scale


@dataclass(frozen=True)
class Receipt:
    txn_id: int
    at: datetime
    amount: Decimal
    customer: str | None  # display name; None = unidentified payer


@dataclass
class CustomerShare:
    name: str
    amount: Decimal
    share: Decimal  # of identified revenue
    receipts: int
    months_active: int
    txn_ids: list[int] = field(default_factory=list)


@dataclass
class Concentration:
    identified: Decimal
    unidentified: Decimal
    customers: int
    top: list[CustomerShare]
    top1_share: Decimal
    top5_share: Decimal
    hhi: int
    level: str  # low | moderate | high
    flags: list[str]


def analyze(receipts: list[Receipt], months: int, top_n: int = 10) -> Concentration:
    groups: dict[str, list[Receipt]] = defaultdict(list)
    names: dict[str, str] = {}
    unidentified = Decimal("0.00")
    for r in receipts:
        key = normalize_party(r.customer) if r.customer else ""
        if not key or "***" in (r.customer or ""):  # masked PromptPay senders are not identifiable
            unidentified += r.amount
            continue
        groups[key].append(r)
        names.setdefault(key, r.customer)  # type: ignore[arg-type]

    identified = sum((r.amount for rs in groups.values() for r in rs), Decimal("0.00"))
    ranked = sorted(groups.items(), key=lambda kv: (-sum(r.amount for r in kv[1]), kv[0]))
    shares: list[CustomerShare] = []
    hhi = Decimal("0")
    for key, rs in ranked:
        amount = sum((r.amount for r in rs), Decimal("0.00"))
        share = (amount / identified) if identified else Decimal("0")
        hhi += (share * 100) ** 2
        shares.append(CustomerShare(names[key], amount, share.quantize(Decimal("0.0001")), len(rs),
                                    len({(r.at.year, r.at.month) for r in rs}), sorted(r.txn_id for r in rs)))
    top1 = shares[0].share if shares else Decimal("0")
    top5 = sum((s.share for s in shares[:5]), Decimal("0"))
    hhi_i = int(hhi.to_integral_value())

    flags: list[str] = []
    if shares and top1 > TOP1_HIGH:
        flags.append(th(f"ลูกค้ารายใหญ่สุด ({shares[0].name}) คิดเป็น {top1:.0%} ของรายได้ที่ระบุตัวลูกค้าได้"))
    if top5 > TOP5_HIGH and len(shares) > 5:
        flags.append(th(f"ลูกค้า 5 รายแรกคิดเป็น {top5:.0%} ของรายได้"))
    if shares and top1 > TOP1_HIGH and shares[0].months_active < max(1, months // 2):
        flags.append(th("ลูกค้ารายใหญ่สุดจ่ายเงินไม่ถึงครึ่งหนึ่งของเดือนที่พิจารณา — รายได้อาจไม่ต่อเนื่อง"))
    level = "high" if (top1 > TOP1_HIGH or hhi_i > HHI_HIGH) else "moderate" if (top5 > TOP5_HIGH or hhi_i > 1500) else "low"
    return Concentration(identified, unidentified, len(shares), shares[:top_n], top1, top5.quantize(Decimal("0.0001")),
                         hhi_i, level, flags)
