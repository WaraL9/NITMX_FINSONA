"""Own-account transfer matching and circular-flow detection (E4-01, E4-02, E4-03).

Step 1 — match legs. A leg is a debit in one in-file account paired with the credit it
produced in another in-file account: same amount (the receiving side may be up to a small
fee lower), credit within [debit - 5 min, debit + window]. When the statement names the
counterparty account, it must be the other in-file account. Credits are bucketed per
destination account and sorted by amount, so each debit is a binary search:
O(n log n) overall rather than comparing every credit with every debit.

Step 2 — find loops. Legs form a temporal directed graph over accounts. A loop is a chain
of 2..max_hops legs where each leg leaves the account the previous one entered, no
earlier than it, with an amount within `decay` of the previous leg, ending back at the
first account within the time window. Each leg belongs to at most one loop; search is
earliest-first, so results are deterministic.
"""

from __future__ import annotations

import bisect
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from app.engine.types import DetectedLoop, EAccount, ETxn, LoopLeg

_LAST4 = re.compile(r"(\d{4})")


def last4(account_no: str | None) -> str | None:
    if not account_no:
        return None
    m = _LAST4.findall(account_no)
    return m[-1] if m else None


@dataclass(frozen=True)
class Leg:
    debit: ETxn
    credit: ETxn
    src: int  # account id
    dst: int

    @property
    def amount(self) -> Decimal:
        return self.debit.debit

    @property
    def at(self):
        return self.debit.posted_at


class _AccountIndex:
    def __init__(self, accounts: list[EAccount]):
        self.by_id = {a.id: a for a in accounts}
        self.by_last4: dict[str, list[EAccount]] = defaultdict(list)
        for a in accounts:
            k = last4(a.account_no)
            if k:
                self.by_last4[k].append(a)

    def resolve(self, account_no: str | None, bank: str | None) -> EAccount | None:
        k = last4(account_no)
        if not k:
            return None
        hits = [a for a in self.by_last4.get(k, []) if not bank or a.bank_code == bank]
        return hits[0] if len(hits) == 1 else None


def match_own_transfers(accounts: list[EAccount], txns: list[ETxn], window: timedelta = timedelta(hours=72),
                        max_fee: Decimal = Decimal("50")) -> list[Leg]:
    idx = _AccountIndex(accounts)
    # Credits per destination account, sorted by amount for binary search.
    credits: dict[int, list[tuple[Decimal, int, ETxn]]] = defaultdict(list)
    for t in txns:
        if t.credit > 0:
            credits[t.account_id].append((t.credit, t.id, t))
    for lst in credits.values():
        lst.sort(key=lambda x: (x[0], x[1]))
    keys = {a: [x[0] for x in lst] for a, lst in credits.items()}

    used: set[int] = set()
    legs: list[Leg] = []
    for d in sorted((t for t in txns if t.debit > 0), key=lambda t: (t.posted_at, t.id)):
        if d.counterparty_account:
            dest = idx.resolve(d.counterparty_account, d.counterparty_bank)
            if dest is None or dest.id == d.account_id:
                continue
            candidates = [dest.id]
        elif d.code.startswith("TR"):
            candidates = [a for a in idx.by_id if a != d.account_id]
        else:
            continue
        src = idx.by_id[d.account_id]
        best: ETxn | None = None
        for dst in candidates:
            lst, ks = credits.get(dst, []), keys.get(dst, [])
            lo = bisect.bisect_left(ks, d.debit - max_fee)
            hi = bisect.bisect_right(ks, d.debit)
            for _, _, c in lst[lo:hi]:
                if c.id in used:
                    continue
                if not (d.posted_at - timedelta(minutes=5) <= c.posted_at <= d.posted_at + window):
                    continue
                if c.counterparty_account and last4(c.counterparty_account) != last4(src.account_no):
                    continue
                if best is None or abs(c.posted_at - d.posted_at) < abs(best.posted_at - d.posted_at):
                    best = c
        if best is not None:
            used.add(best.id)
            legs.append(Leg(d, best, d.account_id, best.account_id))
    return legs


def detect_loops(legs: list[Leg], company_ids: set[int], window: timedelta = timedelta(hours=72),
                 max_hops: int = 4, decay: Decimal = Decimal("0.05")) -> list[DetectedLoop]:
    ordered = sorted(legs, key=lambda l: (l.at, l.debit.id))
    out_by_src: dict[int, list[Leg]] = defaultdict(list)
    for leg in ordered:
        out_by_src[leg.src].append(leg)

    used: set[int] = set()  # debit txn ids

    def extend(path: list[Leg]) -> list[Leg] | None:
        last = path[-1]
        if len(path) >= 2 and last.dst == path[0].src:
            return path
        if len(path) == max_hops:
            return None
        for nxt in out_by_src.get(last.dst, []):
            if nxt.debit.id in used or nxt in path or nxt.at < last.at:
                continue
            if nxt.at - path[0].at > window:
                break  # out_by_src is time-ordered
            if not (last.amount * (1 - decay) <= nxt.amount <= last.amount * Decimal("1.001")):
                continue
            found = extend(path + [nxt])
            if found:
                return found
        return None

    loops: list[DetectedLoop] = []
    for start in ordered:
        if start.debit.id in used:
            continue
        path = extend([start])
        if not path:
            continue
        for leg in path:
            used.add(leg.debit.id)
        loops.append(DetectedLoop(
            id=f"L{len(loops) + 1}",
            legs=[LoopLeg(l.debit.id, l.credit.id, l.src, l.dst, l.amount, l.at) for l in path],
            netted_amount=sum((l.credit.credit for l in path if l.dst in company_ids), Decimal("0.00")),
            hours=round((path[-1].credit.posted_at - path[0].at).total_seconds() / 3600, 1),
        ))
    return loops
