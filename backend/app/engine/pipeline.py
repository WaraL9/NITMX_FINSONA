"""The analysis pipeline: transactions in -> clean cash flow, tiers, loops, watchlist out.

  1. match own-account transfer legs, find loops            (transfers.py)
  2. classify company-account credits and debits             (rules.py)
  3. tier revenue: invoices -> ภ.พ.30 -> context -> watchlist (tiers.py)
  4. apply CA decisions on watchlist items
  5. aggregate the waterfall and costs; self-check that every baht of company inflow
     lands in exactly one bucket

Only company accounts produce revenue or cost. Director/family accounts are read for
context (loops, owner money) but are never the business's income or expense.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from app.engine import rules, tiers
from app.engine.transfers import detect_loops, match_own_transfers
from app.engine.types import (
    ENGINE_VERSION,
    AnalysisResult,
    Decision,
    EAccount,
    EFiling,
    EInvoice,
    ETxn,
    Outcome,
)
from app.core.i18n import th

ZERO = Decimal("0.00")
REVENUE_TIERS = ("T1_golden", "T2_tax", "T3_operational")


def _months(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month + 1


def analyze(
    accounts: list[EAccount],
    txns: list[ETxn],
    invoices: list[EInvoice],
    filings: list[EFiling],
    period_start: date,
    period_end: date,
    decisions: dict[int, Decision] | None = None,
    overrides: dict[int, tuple[str, str]] | None = None,
    progress: Callable[[str], None] | None = None,
) -> AnalysisResult:
    """overrides: txn id -> (value, CA reason); see types.CREDIT_OVERRIDES / DEBIT_OVERRIDES.
    progress: called with each stage name as it completes (E0-07 job progress); no effect on results."""
    decisions = decisions or {}
    overrides = overrides or {}
    timings: dict[str, float] = {}
    clock = time.perf_counter()

    def lap(stage: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        timings[stage] = round((now - clock) * 1000, 2)
        clock = now
        if progress:
            progress(stage)

    company = {a.id for a in accounts if a.owner_type == "company"}
    owners = {a.id for a in accounts if a.owner_type in ("director", "family")}
    family_surnames = {s for a in accounts if a.id in owners if (s := rules.surname(a.account_name))}
    by_id = {t.id: t for t in txns}
    outcomes: dict[int, Outcome] = {}

    # 1. transfers and loops
    legs = match_own_transfers(accounts, txns)
    loops = detect_loops(legs, company)
    loop_of: dict[int, str] = {}
    for lp in loops:
        for leg in lp.legs:
            loop_of[leg.debit_txn_id] = loop_of[leg.credit_txn_id] = lp.id
    for leg in legs:
        lid = loop_of.get(leg.debit.id)
        for t in (leg.debit, leg.credit):
            if lid:
                outcomes[t.id] = Outcome("own_transfer_loop", th(f"เงินโอนวนระหว่างบัญชีตนเอง (วงจร {lid}) — ตัดออก"),
                                         loop_id=lid)
            elif leg.src in owners and leg.dst in company:
                outcomes[t.id] = Outcome("owner_injection", th("เงินโอนจากบัญชีเจ้าของเข้าบริษัท — เป็นเงินทุน ไม่ใช่รายได้"))
            elif leg.src in company and leg.dst in owners:
                outcomes[t.id] = Outcome("owner_drawing", th("บริษัทโอนให้บัญชีเจ้าของ — ไม่ใช่ต้นทุนดำเนินงาน"))
            else:
                outcomes[t.id] = Outcome("own_transfer_internal", th("โอนระหว่างบัญชีของบริษัท — ไม่ใช่รายได้/รายจ่าย"))

    lap("loops")

    # 2. classify everything else
    revenue_candidates: list[ETxn] = []
    for t in txns:
        if t.id in outcomes:
            continue
        if t.account_id not in company:
            outcomes[t.id] = Outcome("personal_account", th("รายการในบัญชีส่วนตัว — ไม่นับเป็นรายได้/ต้นทุนธุรกิจ"))
            continue
        if t.credit > 0:
            tag, reason = rules.tag_company_credit(t, family_surnames)
            outcomes[t.id] = Outcome(tag, reason)
            if tag != "owner_injection":
                revenue_candidates.append(t)
        elif t.debit > 0:
            tag, reason = rules.tag_company_debit(t, family_surnames)
            outcomes[t.id] = Outcome(tag, reason)

    lap("classify")

    # 3. tiers
    party_counts = Counter(rules.normalize_party(t.counterparty_name) for t in revenue_candidates
                           if t.counterparty_name)
    recurring = {p for p, n in party_counts.items() if n >= 2}
    recurring3 = {p for p, n in party_counts.items() if n >= 3}

    customer = [t for t in revenue_candidates if outcomes[t.id].tag == "customer_receipt"]
    matched = tiers.match_invoices(customer, invoices)
    t1_by_month: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for tid, (inv, how) in matched.items():
        o = outcomes[tid]
        o.tier, o.invoice_id = "T1_golden", inv.id
        where = th("ใบกำกับภาษีอิเล็กทรอนิกส์ (e-Tax) ที่อัปโหลด") if inv.source == "etax_upload" else th("ใบแจ้งหนี้ PromptBiz")
        o.reason = th(f"ตรงกับ{where} {inv.invoice_no} ({how})")
        t1_by_month[by_id[tid].posted_at.strftime("%Y-%m")] += by_id[tid].credit

    rest = [t for t in customer if t.id not in matched]
    t2 = tiers.allocate_tax_capacity(rest, {f.period: f for f in filings}, t1_by_month, recurring)
    for tid, reason in t2.items():
        outcomes[tid].tier, outcomes[tid].reason = "T2_tax", reason

    rest = [t for t in revenue_candidates if outcomes[t.id].tier is None]
    for tid, reason in tiers.operational(rest, recurring3).items():
        outcomes[tid].tier, outcomes[tid].reason = "T3_operational", reason

    watchlist = []
    for t in revenue_candidates:
        o = outcomes[t.id]
        if o.tier is not None:
            continue
        o.tier = "T4_unverified"
        item = tiers.watch_item(t, period_end, party_counts.get(rules.normalize_party(t.counterparty_name), 0))
        o.reason = item.note
        watchlist.append(item)
        # 4. CA decisions
        d = decisions.get(t.id)
        if d == "accepted":
            o.tier, o.reason = "T3_operational", th("CA รับรองเป็นรายได้จากการค้า (ดูบันทึกเหตุผล)")
            o.tag = "ca_accepted"
        elif d == "excluded":
            o.tag = "ca_excluded"
    watchlist.sort(key=lambda w: (-w.score, -by_id[w.txn_id].credit))

    # CA overrides win over every engine conclusion.
    for tid, (value, why) in overrides.items():
        t = by_id.get(tid)
        if t is None or t.account_id not in company:
            continue
        o = outcomes[tid]
        o.overridden = True
        o.reason = th(f"CA override: {why} (เดิม: {o.reason})")
        if t.credit > 0:
            if value == "non_revenue":
                o.tier, o.tag = None, "ca_non_revenue"
            else:
                o.tier = value
                o.tag = "ca_unverified" if value == "T4_unverified" else "ca_revenue"
        elif t.debit > 0:
            o.tag = "ca_business_cost" if value == "business_cost" else "ca_non_business"
    lap("tiers")

    # 5. aggregate
    def total(ids_filter) -> Decimal:
        return sum((t.credit for t in txns if t.account_id in company and ids_filter(outcomes[t.id])), ZERO)

    tier_totals = {k: total(lambda o, k=k: o.tier == k) for k in REVENUE_TIERS}
    unverified_pending = total(lambda o: o.tier == "T4_unverified" and o.tag != "ca_excluded")
    unverified_excluded = total(lambda o: o.tag == "ca_excluded")
    accepted = total(lambda o: o.tag == "ca_accepted")
    waterfall = {
        "gross_raw_inflow": total(lambda o: True),
        "own_account_loops": total(lambda o: o.tag == "own_transfer_loop"),
        "internal_transfers": total(lambda o: o.tag == "own_transfer_internal"),
        "owner_family_inflow": total(lambda o: o.tag == "owner_injection"),
        "unverified_pending": unverified_pending,
        "unverified_excluded": unverified_excluded,
        "accepted_by_ca": accepted,
        "ca_non_revenue": total(lambda o: o.tag == "ca_non_revenue"),
        "verified_operating_revenue": sum(tier_totals.values(), ZERO),
    }
    accounted = (waterfall["own_account_loops"] + waterfall["internal_transfers"] + waterfall["ca_non_revenue"]
                 + waterfall["owner_family_inflow"] + unverified_pending + unverified_excluded
                 + waterfall["verified_operating_revenue"])

    debits = [t for t in txns if t.account_id in company and t.debit > 0]
    by_tag: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for t in debits:
        by_tag[outcomes[t.id].tag] += t.debit
    cost_tags = rules.COST_TAGS | {"ca_business_cost"}
    business = sum((v for k, v in by_tag.items() if k in cost_tags), ZERO)
    months = _months(period_start, period_end)
    costs = {
        "business_operating": business,
        **{f"cost_{k}": by_tag.get(k, ZERO) for k in sorted(cost_tags)},
        "household": by_tag.get("household", ZERO) + by_tag.get("owner_drawing", ZERO),
        "debt_service_total": by_tag.get("debt_service", ZERO),
        "own_transfers_out": by_tag.get("own_transfer_loop", ZERO) + by_tag.get("own_transfer_internal", ZERO),
    }
    cfo = waterfall["verified_operating_revenue"] - business
    lap("aggregate")
    notes = []
    if accounted != waterfall["gross_raw_inflow"]:
        notes.append(f"waterfall does not reconcile: {accounted} vs {waterfall['gross_raw_inflow']}")

    return AnalysisResult(
        engine_version=ENGINE_VERSION,
        months=months,
        outcomes=outcomes,
        loops=loops,
        watchlist=watchlist,
        waterfall=waterfall,
        tiers={**tier_totals, "T4_unverified": unverified_pending + unverified_excluded},
        costs=costs,
        clean_cash_flow_period=cfo,
        clean_cash_flow_monthly=(cfo / months).quantize(Decimal("0.01")),
        existing_debt_monthly=(costs["debt_service_total"] / months).quantize(Decimal("0.01")),
        reconciles=accounted == waterfall["gross_raw_inflow"],
        notes=notes,
        timings_ms=timings,
    )
