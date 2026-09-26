"""Run the engine over a case and persist the results.

load case -> sync PromptBiz invoices + utility/rent history (connectors) -> engine ->
alt-data haircut, cash-pattern evidence, decision drivers -> write tag/tier/loop/reason
onto each transaction, upsert Watchlist items (keeping CA decisions), store an Analysis.
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.base import ConnectorError
from app.connectors.promptbiz import get_invoice_source
from app.connectors.utility import get_utility_source
from app.engine import altdata, cash_pattern
from app.engine.explain import ExplainInputs, explain
from app.engine.pipeline import analyze
from app.engine.types import AnalysisResult, EAccount, EFiling, EInvoice, ETxn, Policy
from app.models import (
    Account,
    AltDataRecord,
    Analysis,
    Case,
    Invoice,
    TagOverride,
    TaxFiling,
    Transaction,
    WatchlistItem,
)

# Bank credit policy (E6-08 makes this editable per product).
DEFAULT_POLICY = Policy()
from app.services import audit


class AnalysisError(Exception):
    pass


def sync_promptbiz(db: Session, case: Case) -> dict:
    """Pull the seller's e-invoices through the PromptBiz connector (sandbox today)."""
    source = get_invoice_source()
    if not case.tax_id:
        return {"source": source.name, "mode": source.mode, "fetched": 0, "note": "case has no tax ID"}
    # Consent capture is E14-02; until then the case id stands in as the consent reference.
    records = source.fetch_invoices(case.tax_id, consent_token=f"case-{case.id}")
    db.execute(delete(Invoice).where(Invoice.case_id == case.id, Invoice.source.like("promptbiz_%")))
    db.add_all(Invoice(
        case_id=case.id, source=f"promptbiz_{source.mode}", invoice_no=r.invoice_no, issue_date=r.issue_date,
        seller_tax_id=r.seller_tax_id, buyer_name=r.buyer_name, buyer_tax_id=r.buyer_tax_id,
        subtotal=r.subtotal, vat=r.vat, amount=r.total, wht=r.wht, paid_amount=r.paid_amount,
        paid_at=r.paid_at, settlement_ref=r.settlement_ref,
    ) for r in records)
    db.flush()
    return {"source": source.name, "mode": source.mode, "fetched": len(records)}


def sync_alt_data(db: Session, case: Case) -> dict:
    """Pull utility & rent payment history through the utility connector (sandbox today)."""
    source = get_utility_source()
    if not case.tax_id:
        return {"source": source.name, "mode": source.mode, "fetched": 0, "note": "case has no tax ID"}
    bills = source.fetch_bills(case.tax_id, consent_token=f"case-{case.id}", scenario=case.sandbox_alt_scenario)
    db.execute(delete(AltDataRecord).where(AltDataRecord.case_id == case.id))
    db.add_all(AltDataRecord(
        case_id=case.id, kind=b["kind"], period=b["period"], due_date=date.fromisoformat(b["due_date"]),
        paid_date=date.fromisoformat(b["paid_date"]) if b.get("paid_date") else None,
        amount=Decimal(b["amount"]), source=f"utility_{source.mode}",
    ) for b in bills)
    db.flush()
    return {"source": source.name, "mode": source.mode, "fetched": len(bills), "scenario": case.sandbox_alt_scenario}


def _period(case: Case, txns: list[Transaction]) -> tuple[date, date]:
    if case.period_start and case.period_end:
        return case.period_start, case.period_end
    if not txns:
        raise AnalysisError("no transactions to analyse — upload statements first")
    return min(t.posted_at for t in txns).date(), max(t.posted_at for t in txns).date()


def _money(d: dict[str, Decimal]) -> dict[str, str]:
    return {k: f"{v:.2f}" for k, v in d.items()}


def serialize(r: AnalysisResult, sync: dict | None, period: tuple[date, date]) -> dict:
    return {
        "engine_version": r.engine_version,
        "period_start": period[0].isoformat(),
        "period_end": period[1].isoformat(),
        "months": r.months,
        "reconciles": r.reconciles,
        "notes": r.notes,
        "waterfall": _money(r.waterfall),
        "tiers": _money(r.tiers),
        "costs": _money(r.costs),
        "clean_cash_flow_period": f"{r.clean_cash_flow_period:.2f}",
        "clean_cash_flow_monthly": f"{r.clean_cash_flow_monthly:.2f}",
        "existing_debt_monthly": f"{r.existing_debt_monthly:.2f}",
        "loops": [
            {
                "id": lp.id,
                "netted_amount": f"{lp.netted_amount:.2f}",
                "hours": lp.hours,
                "legs": [
                    {"debit_txn_id": l.debit_txn_id, "credit_txn_id": l.credit_txn_id,
                     "from_account_id": l.from_account_id, "to_account_id": l.to_account_id,
                     "amount": f"{l.amount:.2f}", "at": l.at.isoformat()}
                    for l in lp.legs
                ],
            }
            for lp in r.loops
        ],
        "watchlist_count": len(r.watchlist),
        "connector": sync,
        "timings_ms": r.timings_ms,
    }


def run_analysis(db: Session, case_id: int, sync_invoices: bool = True, user_id: int | None = None,
                 ip: str | None = None, trigger: str = "manual") -> Analysis:
    case = db.get(Case, case_id)
    if case is None:
        raise AnalysisError(f"case {case_id} not found")
    sync = alt_sync = None
    if sync_invoices:
        try:
            sync = sync_promptbiz(db, case)
        except ConnectorError as e:
            sync = {"error": str(e)}
        try:
            alt_sync = sync_alt_data(db, case)
        except ConnectorError as e:
            alt_sync = {"error": str(e)}
    else:
        # Re-runs after a CA decision reuse the data already synced; keep its provenance.
        previous = latest_analysis(db, case_id)
        sync = previous.result.get("connector") if previous else None
        alt_sync = previous.result.get("alt_connector") if previous else None

    accounts = list(db.scalars(select(Account).where(Account.case_id == case_id)))
    rows = list(db.scalars(select(Transaction).where(Transaction.case_id == case_id)))
    if not rows:
        raise AnalysisError("no transactions to analyse — upload statements first")
    invoices = list(db.scalars(select(Invoice).where(Invoice.case_id == case_id)))
    filings = list(db.scalars(select(TaxFiling).where(TaxFiling.case_id == case_id)))
    existing_items = {w.transaction_id: w for w in db.scalars(select(WatchlistItem).where(WatchlistItem.case_id == case_id))}
    decisions = {tid: w.status for tid, w in existing_items.items() if w.status in ("accepted", "excluded")}
    overrides = {o.transaction_id: (o.value, o.reason)
                 for o in db.scalars(select(TagOverride).where(TagOverride.case_id == case_id))}
    period = _period(case, rows)

    started = time.perf_counter()
    result = analyze(
        [EAccount(a.id, a.bank_code, a.account_no_masked, a.account_name, a.owner_type) for a in accounts],
        [ETxn(t.id, t.account_id, t.posted_at, t.code or "", t.description, t.debit, t.credit,
              t.counterparty_name, t.counterparty_account, t.counterparty_bank) for t in rows],
        [EInvoice(i.id, i.invoice_no, i.issue_date, i.buyer_name, i.amount, i.subtotal) for i in invoices],
        [EFiling(f.period, f.sales, f.output_vat) for f in filings],
        period[0],
        period[1],
        decisions,
        overrides,
    )
    duration_ms = int((time.perf_counter() - started) * 1000)

    for t in rows:
        o = result.outcomes[t.id]
        t.tag, t.tier, t.loop_id, t.tag_reason, t.invoice_id = o.tag, o.tier, o.loop_id, o.reason, o.invoice_id
        t.tag_source = "ca" if o.overridden else "rule"
    _llm_annotations(db, rows, result)
    for inv in invoices:
        inv.matched_transaction_id = None
    inv_by_id = {i.id: i for i in invoices}
    for tid, o in result.outcomes.items():
        if o.invoice_id:
            inv_by_id[o.invoice_id].matched_transaction_id = tid

    # Watchlist: keep decided items and their reasons; refresh pending ones.
    current = {w.txn_id: w for w in result.watchlist}
    for tid, item in existing_items.items():
        if tid not in current and item.status == "pending":
            db.delete(item)
    for tid, w in current.items():
        item = existing_items.get(tid)
        if item is None:
            db.add(WatchlistItem(case_id=case_id, transaction_id=tid, suspicion_score=w.score, system_note=w.note))
        else:
            item.suspicion_score, item.system_note = w.score, w.note

    payload = serialize(result, sync, period)
    payload.update(_evidence(db, case, result, rows, period, alt_sync))
    analysis = Analysis(case_id=case_id, engine_version=result.engine_version, duration_ms=duration_ms,
                        result=payload)
    db.add(analysis)
    db.flush()
    audit.log(db, "analysis_run", case_id=case_id, user_id=user_id, ip=ip, target_type="analysis",
              target_id=analysis.id, after={
                  "trigger": trigger,
                  "engine_version": result.engine_version,
                  "verified_operating_revenue": f"{result.waterfall['verified_operating_revenue']:.2f}",
                  "clean_cash_flow_monthly": f"{result.clean_cash_flow_monthly:.2f}",
                  "reconciles": result.reconciles,
              })
    if case.status in ("draft", "processing"):
        case.status = "in_review"
    db.commit()
    db.refresh(analysis)
    return analysis


def _llm_annotations(db: Session, rows: list[Transaction], r: AnalysisResult) -> None:
    """E7-02: ask the LLM about rows the rules left unlabelled. Annotation only — the
    engine's tags (and therefore every figure) are unchanged; a CA can apply the
    suggestion with an override."""
    from app.ai import tagging

    todo = [t for t in rows if r.outcomes[t.id].tag == "other_expense" and not r.outcomes[t.id].overridden]
    for s in tagging.suggest(db, [(t.id, t.description, t.counterparty_name) for t in todo]):
        t = next(x for x in todo if x.id == s.txn_id)
        t.tag_source = "llm"
        t.tag_reason = f"{t.tag_reason} · AI แนะนำหมวด {s.tag} (ความเชื่อมั่น {s.confidence:.0%}): {s.rationale}"


def _evidence(db: Session, case: Case, r: AnalysisResult, rows: list[Transaction], period: tuple[date, date],
              alt_sync: dict | None) -> dict:
    """Alt-data haircut (E6-06), cash-pattern evidence (E4-06) and decision drivers (E7-06)."""
    bills = [altdata.EBill(b.kind, b.period, b.due_date, b.paid_date, b.amount)
             for b in db.scalars(select(AltDataRecord).where(AltDataRecord.case_id == case.id))]
    alt = altdata.evaluate(bills, as_of=period[1])
    months = r.months
    cfo_m = r.clean_cash_flow_monthly
    sizing_cfo = (cfo_m * (1 - alt.haircut)).quantize(Decimal("0.01"))

    withdrawals = [ETxn(t.id, t.account_id, t.posted_at, t.code or "", t.description, t.debit, t.credit)
                   for t in rows if r.outcomes[t.id].tag == "cash_withdrawal"]
    cash = cash_pattern.detect(withdrawals)

    _, drivers = explain(ExplainInputs(
        months=months, cfo_monthly=sizing_cfo, cfo_monthly_before_haircut=cfo_m,
        existing_debt_monthly=r.existing_debt_monthly, annual_rate=case.annual_rate, tenor_months=case.tenor_months,
        requested=case.requested_amount, tiers=r.tiers, household=r.costs["household"],
        pending_unverified=r.waterfall["unverified_pending"], loops=r.waterfall["own_account_loops"],
        owner_inflow=r.waterfall["owner_family_inflow"], haircut=alt.haircut,
        cash_pattern_detected=cash.detected, cash_total=cash.total, policy=DEFAULT_POLICY,
    ))
    wf, costs, tiers = r.waterfall, r.costs, r.tiers
    return {
        "revenue_monthly": f"{wf['verified_operating_revenue'] / months:.2f}",
        "costs_monthly": f"{costs['business_operating'] / months:.2f}",
        "t1_monthly": f"{tiers['T1_golden'] / months:.2f}",
        "sizing_cfo_monthly": f"{sizing_cfo:.2f}",
        "alt_data": {
            "months_covered": alt.months_covered, "bills": alt.bills, "on_time": alt.on_time,
            "late_30": alt.late_30, "late_60_or_unpaid": alt.late_60_or_unpaid, "haircut": str(alt.haircut),
            "ews": alt.ews, "liveness_confirmed": alt.liveness_confirmed, "signals": alt.signals,
        },
        "alt_connector": alt_sync,
        "cash_pattern": {
            "detected": cash.detected, "count": cash.count, "total": f"{cash.total:.2f}",
            "average": f"{cash.average:.2f}", "top_weekdays": cash.top_weekdays,
            "weekday_share": cash.weekday_share, "morning_share": cash.morning_share,
        },
        "drivers": [{"kind": d.kind, "key": d.key, "title": d.title, "detail": d.detail,
                     "impact": f"{d.impact:.2f}", "metric": d.metric} for d in drivers],
    }


def latest_analysis(db: Session, case_id: int) -> Analysis | None:
    return db.scalar(select(Analysis).where(Analysis.case_id == case_id).order_by(Analysis.id.desc()).limit(1))
