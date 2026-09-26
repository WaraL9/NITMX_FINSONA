"""Run the engine over a case and persist the results.

load case -> sync PromptBiz invoices (connector) -> engine -> write tag/tier/loop/reason
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
from app.engine.pipeline import analyze
from app.engine.types import AnalysisResult, EAccount, EFiling, EInvoice, ETxn
from app.models import Account, Analysis, Case, Invoice, TagOverride, TaxFiling, Transaction, WatchlistItem
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
    sync = None
    if sync_invoices:
        try:
            sync = sync_promptbiz(db, case)
        except ConnectorError as e:
            sync = {"error": str(e)}
    else:
        # Re-runs after a CA decision reuse the invoices already synced; keep their provenance.
        previous = latest_analysis(db, case_id)
        sync = previous.result.get("connector") if previous else None

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

    analysis = Analysis(case_id=case_id, engine_version=result.engine_version, duration_ms=duration_ms,
                        result=serialize(result, sync, period))
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


def latest_analysis(db: Session, case_id: int) -> Analysis | None:
    return db.scalar(select(Analysis).where(Analysis.case_id == case_id).order_by(Analysis.id.desc()).limit(1))
