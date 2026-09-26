"""Revenue triangulation into verification tiers (E5-01..E5-04).

T1 Golden         receipt matched to a PromptBiz / e-Tax invoice
                  (amount = invoice total, or total minus 1/2/3% WHT on the subtotal;
                   buyer name matches; paid 0-120 days after issue)
T2 Tax-verified   within the month's ภ.พ.30 declared sales (+ output VAT, since receipts
                  include VAT) after T1 receipts are taken out. Transfers from recurring
                  customers are allocated first; a receipt is never split.
T3 Operational    context-supported: high-velocity PromptPay micro-receipts, or a
                  recurring customer beyond the declared capacity
T4 Unverified     everything else -> Watchlist (never counted until a CA accepts it)
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.engine.rules import is_individual, normalize_party
from app.engine.types import EFiling, EInvoice, ETxn, WatchItem

AMOUNT_TOL = Decimal("1.00")
WHT_RATES = (Decimal("0.01"), Decimal("0.02"), Decimal("0.03"))
PAY_WINDOW = timedelta(days=120)
PP_VELOCITY_MIN = 20  # PromptPay receipts per account-month
PP_MICRO_MAX = Decimal("50000")
MEMO_RE = re.compile(r"x{3}-x-x\d{4}-x\s+(.+)$")


def _q(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), ROUND_HALF_UP)


def _names_match(a: str, b: str) -> bool:
    na, nb = normalize_party(a), normalize_party(b)
    return bool(na) and bool(nb) and (na == nb or na in nb or nb in na)


def match_invoices(receipts: list[ETxn], invoices: list[EInvoice]) -> dict[int, tuple[EInvoice, str]]:
    """receipt txn id -> (invoice, how it matched). One-to-one, earliest receipt first."""
    by_buyer: dict[str, list[EInvoice]] = defaultdict(list)
    for inv in invoices:
        by_buyer[normalize_party(inv.buyer_name)].append(inv)
    used: set[int] = set()
    out: dict[int, tuple[EInvoice, str]] = {}
    for r in sorted(receipts, key=lambda t: (t.posted_at, t.id)):
        pool = by_buyer.get(normalize_party(r.counterparty_name), [])
        if not pool:
            pool = [i for i in invoices if _names_match(i.buyer_name, r.counterparty_name or "")]
        best: tuple[Decimal, int, EInvoice, str] | None = None
        for inv in pool:
            if inv.id in used:
                continue
            days = (r.posted_at.date() - inv.issue_date).days
            if not (0 <= days <= PAY_WINDOW.days):
                continue
            options = [(inv.total, "ยอดตรงกับใบแจ้งหนี้")]
            options += [(inv.total - _q(inv.subtotal * w), f"ยอดสุทธิหลังหักภาษี ณ ที่จ่าย {int(w * 100)}%")
                        for w in WHT_RATES]
            for expected, how in options:
                diff = abs(r.credit - expected)
                if diff <= AMOUNT_TOL and (best is None or (diff, days) < (best[0], best[1])):
                    best = (diff, days, inv, how)
        if best:
            used.add(best[2].id)
            out[r.id] = (best[2], best[3])
    return out


def allocate_tax_capacity(candidates: list[ETxn], filings: dict[str, EFiling],
                          t1_by_month: dict[str, Decimal], recurring: set[str]) -> dict[int, str]:
    """receipt txn id -> reason, for receipts that fit within declared ภ.พ.30 sales."""
    by_month: dict[str, list[ETxn]] = defaultdict(list)
    for t in candidates:
        by_month[t.posted_at.strftime("%Y-%m")].append(t)
    out: dict[int, str] = {}
    for month, txns in by_month.items():
        f = filings.get(month)
        if f is None:
            continue
        remaining = f.sales + f.output_vat - t1_by_month.get(month, Decimal("0.00"))
        order = sorted(txns, key=lambda t: (normalize_party(t.counterparty_name) not in recurring, t.posted_at, t.id))
        for t in order:
            if t.credit <= remaining:
                remaining -= t.credit
                out[t.id] = f"อยู่ในยอดขายที่ยื่น ภ.พ.30 เดือน {month}"
    return out


def operational(candidates: list[ETxn], recurring3: set[str]) -> dict[int, str]:
    pp_count: Counter[tuple[int, str]] = Counter()
    for t in candidates:
        if t.code == "PP-IN" or "พร้อมเพย์" in t.description:
            pp_count[(t.account_id, t.posted_at.strftime("%Y-%m"))] += 1
    out: dict[int, str] = {}
    for t in candidates:
        is_pp = t.code == "PP-IN" or "พร้อมเพย์" in t.description
        n = pp_count[(t.account_id, t.posted_at.strftime("%Y-%m"))]
        if is_pp and n >= PP_VELOCITY_MIN and t.credit <= PP_MICRO_MAX:
            out[t.id] = f"รับพร้อมเพย์รายย่อยสม่ำเสมอ ({n} รายการในเดือน) — ฐานลูกค้ารายย่อยจริง"
        elif not is_pp and normalize_party(t.counterparty_name) in recurring3:
            out[t.id] = "ลูกค้าประจำ (รับชำระซ้ำหลายครั้ง) แต่ยอดเกินที่ยื่นภาษี"
    return out


def watch_item(t: ETxn, period_end: date, counterparty_count: int) -> WatchItem:
    score = 0.5
    notes: list[str] = []
    if t.code == "CD" or "ฝากเงินสด" in t.description:
        score += 0.3
        notes.append("ฝากเงินสดก้อนใหญ่ ไม่มีเอกสารการค้ารองรับ")
    else:
        memo = MEMO_RE.search(t.description)
        if memo:
            notes.append(f"ไม่มีใบแจ้งหนี้ PromptBiz หรือยอดใน ภ.พ.30 แต่พบข้อความ “{memo.group(1).strip()}”")
        else:
            notes.append("ไม่มีใบแจ้งหนี้ PromptBiz หรือยอดใน ภ.พ.30 รองรับ")
        if is_individual(t.counterparty_name):
            score += 0.1
            notes.append("โอนจากบุคคลธรรมดา")
    if t.counterparty_name and counterparty_count <= 1:
        score += 0.05
        notes.append("คู่โอนรายนี้ปรากฏครั้งเดียวในช่วงข้อมูล")
    if (period_end - t.posted_at.date()).days <= 14:
        score += 0.15
        notes.append("เกิดขึ้นช่วงใกล้ยื่นขอสินเชื่อ")
    if t.credit >= Decimal("500000"):
        score += 0.1
    return WatchItem(t.id, round(min(score, 0.99), 2), " · ".join(notes))
