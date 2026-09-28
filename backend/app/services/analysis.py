"""Run the engine over a case and persist the results.

load case -> sync PromptBiz invoices + utility/rent history (connectors) -> engine ->
alt-data haircut, cash-pattern evidence, decision drivers -> write tag/tier/loop/reason
onto each transaction, upsert Watchlist items (keeping CA decisions), store an Analysis.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.base import ConnectorError
from app.connectors.promptbiz import get_invoice_source
from app.connectors.utility import get_utility_source
from app.engine import altdata, anomalies, cash_pattern, concentration
from app.engine.explain import ExplainInputs, explain
from app.engine.pipeline import analyze
from app.engine.types import AnalysisResult, EAccount, EFiling, EInvoice, ETxn, Policy
from app.models import (
    Account,
    AltDataRecord,
    Analysis,
    Case,
    Document,
    Invoice,
    TagOverride,
    TaxFiling,
    Transaction,
    WatchlistItem,
)

# Fallback when no policy row exists yet; the live policy comes from services.policy.
DEFAULT_POLICY = Policy()
from app.services import audit, bills as bills_svc, consent, ocr_review
from app.services import policy as policy_svc


class AnalysisError(Exception):
    pass


def sync_promptbiz(db: Session, case: Case) -> dict:
    """Pull the seller's e-invoices through the PromptBiz connector (sandbox today)."""
    source = get_invoice_source()
    grant = consent.has(db, case.id, "promptbiz_data")
    if grant is None:
        # No consent: never fetch, and drop anything fetched under an earlier grant.
        db.execute(delete(Invoice).where(Invoice.case_id == case.id, Invoice.source.like("promptbiz_%")))
        return {"source": source.name, "mode": source.mode, "fetched": 0, "consent": False,
                "note": "ไม่มีความยินยอมให้ดึงข้อมูล PromptBiz"}
    if not case.tax_id:
        return {"source": source.name, "mode": source.mode, "fetched": 0, "note": "case has no tax ID"}
    records = source.fetch_invoices(case.tax_id, consent_token=f"consent-{grant.id}")
    db.execute(delete(Invoice).where(Invoice.case_id == case.id, Invoice.source.like("promptbiz_%")))
    db.add_all(Invoice(
        case_id=case.id, source=f"promptbiz_{source.mode}", invoice_no=r.invoice_no, issue_date=r.issue_date,
        seller_tax_id=r.seller_tax_id, buyer_name=r.buyer_name, buyer_tax_id=r.buyer_tax_id,
        subtotal=r.subtotal, vat=r.vat, amount=r.total, wht=r.wht, paid_amount=r.paid_amount,
        paid_at=r.paid_at, settlement_ref=r.settlement_ref,
    ) for r in records)
    db.flush()
    return {"source": source.name, "mode": source.mode, "fetched": len(records), "consent": True}


def sync_alt_data(db: Session, case: Case) -> dict:
    """Pull utility & rent payment history through the utility connector (sandbox today)."""
    source = get_utility_source()
    grant = consent.has(db, case.id, "utility_data")
    if grant is None:
        db.execute(delete(AltDataRecord).where(AltDataRecord.case_id == case.id, AltDataRecord.source.like("utility_%")))
        return {"source": source.name, "mode": source.mode, "fetched": 0, "consent": False,
                "note": "ไม่มีความยินยอมให้ดึงประวัติค่าสาธารณูปโภค/ค่าเช่า"}
    if not case.tax_id:
        return {"source": source.name, "mode": source.mode, "fetched": 0, "note": "case has no tax ID"}
    bills = source.fetch_bills(case.tax_id, consent_token=f"consent-{grant.id}", scenario=case.sandbox_alt_scenario)
    db.execute(delete(AltDataRecord).where(AltDataRecord.case_id == case.id, AltDataRecord.source.like("utility_%")))
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


@dataclass
class EngineInputs:
    """Everything the engine reads for a case, loaded once (E8-12 re-runs it with other decisions)."""
    accounts: list[Account]
    rows: list[Transaction]  # analysed rows (OCR-held rows excluded)
    held: list[Transaction]
    invoices: list[Invoice]
    usable_invoices: list[Invoice]
    etax_duplicates: list[str]
    filings: list[TaxFiling]
    existing_items: dict[int, WatchlistItem]
    decisions: dict[int, str]
    overrides: dict[int, tuple[str, str]]
    period: tuple[date, date]


def load_inputs(db: Session, case: Case) -> EngineInputs:
    case_id = case.id
    accounts = list(db.scalars(select(Account).where(Account.case_id == case_id)))
    all_rows = list(db.scalars(select(Transaction).where(Transaction.case_id == case_id)))
    if not all_rows:
        raise AnalysisError("no transactions to analyse — upload statements first")
    # OCR rows whose amount is in doubt stay out of every figure until a CA checks them (E2-09).
    held = [t for t in all_rows if ocr_review.amount_uncertain(t)]
    held_ids = {t.id for t in held}
    rows = [t for t in all_rows if t.id not in held_ids]
    invoices = list(db.scalars(select(Invoice).where(Invoice.case_id == case_id)))
    # E2-13: an uploaded e-Tax invoice that PromptBiz also reports is the same sale. Keep the
    # network copy only, so one sale can never verify two receipts.
    on_network = {i.invoice_no for i in invoices if i.source.startswith("promptbiz_")}
    etax_duplicates = sorted(i.invoice_no for i in invoices if i.source == "etax_upload" and i.invoice_no in on_network)
    # An invoice read uncertainly from a scan verifies nothing until a CA has checked it (E2-09).
    usable = [i for i in invoices if not (i.source == "etax_upload" and i.invoice_no in on_network)
              and i.review_status != "pending"]
    filings = list(db.scalars(select(TaxFiling).where(TaxFiling.case_id == case_id)))
    existing_items = {w.transaction_id: w for w in db.scalars(select(WatchlistItem).where(WatchlistItem.case_id == case_id))}
    decisions = {tid: w.status for tid, w in existing_items.items() if w.status in ("accepted", "excluded")}
    overrides = {o.transaction_id: (o.value, o.reason)
                 for o in db.scalars(select(TagOverride).where(TagOverride.case_id == case_id))}
    return EngineInputs(accounts, rows, held, invoices, usable, etax_duplicates, filings, existing_items, decisions,
                        overrides, _period(case, rows))


def run_engine(inp: EngineInputs, decisions: dict[int, str],
               progress: Callable[[str], None] | None = None) -> AnalysisResult:
    """The deterministic engine over loaded inputs; writes nothing."""
    return analyze(
        [EAccount(a.id, a.bank_code, a.account_no_masked, a.account_name, a.owner_type) for a in inp.accounts],
        [ETxn(t.id, t.account_id, t.posted_at, t.code or "", t.description, t.debit, t.credit,
              t.counterparty_name, t.counterparty_account, t.counterparty_bank) for t in inp.rows],
        [EInvoice(i.id, i.invoice_no, i.issue_date, i.buyer_name, i.amount, i.subtotal, i.source)
         for i in inp.usable_invoices],
        [EFiling(f.period, f.sales, f.output_vat) for f in inp.filings],
        inp.period[0],
        inp.period[1],
        decisions,
        inp.overrides,
        progress,
    )


def run_analysis(db: Session, case_id: int, sync_invoices: bool = True, user_id: int | None = None,
                 ip: str | None = None, trigger: str = "manual",
                 progress: Callable[[str], None] | None = None) -> Analysis:
    """progress (E0-07): called with each stage key as it completes — sync, load, the engine's
    loops/classify/tiers/aggregate, evidence, save."""
    step = progress or (lambda _stage: None)
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

    step("sync")
    inp = load_inputs(db, case)
    step("load")
    rows, held, invoices, etax_duplicates, existing_items, period = (
        inp.rows, inp.held, inp.invoices, inp.etax_duplicates, inp.existing_items, inp.period)

    started = time.perf_counter()
    result = run_engine(inp, inp.decisions, progress)
    duration_ms = int((time.perf_counter() - started) * 1000)

    for t in rows:
        o = result.outcomes[t.id]
        t.tag, t.tier, t.loop_id, t.tag_reason, t.invoice_id = o.tag, o.tier, o.loop_id, o.reason, o.invoice_id
        t.tag_source = "ca" if o.overridden else "rule"
    for t in held:
        t.tag, t.tier, t.loop_id, t.invoice_id, t.tag_source = ocr_review.HELD_TAG, None, None, None, "rule"
        t.tag_reason = "OCR อ่านจำนวนเงินไม่มั่นใจ — ยังไม่นำมาคำนวณจนกว่าเจ้าหน้าที่จะตรวจทาน"
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
    db.flush()
    _evidence_hints(db, case)

    payload = serialize(result, sync, period)
    payload["ocr_held"] = {"rows": len(held), "credit": f"{sum((t.credit for t in held), Decimal('0')):.2f}",
                           "debit": f"{sum((t.debit for t in held), Decimal('0')):.2f}"}
    etax = [i for i in invoices if i.source == "etax_upload"]
    payload["etax"] = {"uploaded": len(etax), "duplicates_of_promptbiz": etax_duplicates,
                       "matched": sum(1 for i in etax if i.matched_transaction_id is not None)}
    payload.update(_evidence(db, case, result, rows, period, alt_sync))
    step("evidence")
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
    step("save")
    return analysis


def sizing_tenor(case: Case, result: dict) -> int:
    """The tenor every sizing uses: the requested one, capped by a lease ending sooner (E6-06)."""
    cap = (result.get("alt_data") or {}).get("tenor_cap_months")
    return min(case.tenor_months, cap) if cap else case.tenor_months


def _evidence_hints(db: Session, case: Case) -> None:
    """E7-05: suggest what would verify each open Watchlist item. Advice only — no figure
    depends on it. Template hints are retried each run so they upgrade once an LLM answers."""
    from app.ai.evidence_hint import HintInput, suggest

    todo = [w for w in db.scalars(select(WatchlistItem).where(WatchlistItem.case_id == case.id,
                                                              WatchlistItem.status.in_(("pending", "queried"))))
            if not w.evidence_hint or w.evidence_hint.get("source") == "template"]
    if not todo:
        return
    txns = {t.id: t for t in db.scalars(select(Transaction).where(Transaction.id.in_([w.transaction_id for w in todo])))}
    hints = suggest(db, [HintInput(w.id, txns[w.transaction_id].description, txns[w.transaction_id].counterparty_name,
                                   txns[w.transaction_id].code or "", txns[w.transaction_id].credit,
                                   txns[w.transaction_id].posted_at, w.system_note) for w in todo],
                    case.industry, case_id=case.id)
    for w in todo:
        w.evidence_hint = hints[w.id].to_json()


def _llm_annotations(db: Session, rows: list[Transaction], r: AnalysisResult) -> None:
    """E7-02: ask the LLM about rows the rules left unlabelled. Annotation only — the
    engine's tags (and therefore every figure) are unchanged; a CA can apply the
    suggestion with an override."""
    from app.ai import tagging

    todo = [t for t in rows if r.outcomes[t.id].tag == "other_expense" and not r.outcomes[t.id].overridden]
    case_id = rows[0].case_id if rows else None
    for s in tagging.suggest(db, [(t.id, t.description, t.counterparty_name) for t in todo], case_id=case_id):
        t = next(x for x in todo if x.id == s.txn_id)
        t.tag_source = "llm"
        t.tag_reason = f"{t.tag_reason} · AI แนะนำหมวด {s.tag} (ความเชื่อมั่น {s.confidence:.0%}): {s.rationale}"


def _bank_mismatches(db: Session, case: Case) -> list[dict]:
    """E3-04: uploaded statements that the bank's own record (dStatement) contradicts."""
    out = []
    for d in db.scalars(select(Document).where(Document.case_id == case.id, Document.parser.like("dstatement%"))):
        v = (d.parse_report or {}).get("verification")
        if not v or not (v["differs_count"] or v["case_only_count"] or v["bank_only_count"]):
            continue
        ids = [x["transaction_id"] for x in v["differs"]] + v["case_only"]
        parts = [f"ยอดต่างจากธนาคาร {v['differs_count']} รายการ" if v["differs_count"] else "",
                 f"ไม่มีในบันทึกธนาคาร {v['case_only_count']} รายการ" if v["case_only_count"] else "",
                 f"ธนาคารมีแต่ไม่อยู่ในไฟล์ที่อัปโหลด {v['bank_only_count']} รายการ" if v["bank_only_count"] else ""]
        amount = sum((Decimal(x["debit"]) + Decimal(x["credit"]) for x in v["bank_only"]), Decimal("0"))
        out.append({
            "kind": "bank_record_mismatch", "severity": "high",
            "title": f"สเตทเมนต์ {d.parse_report.get('bank_code')} {d.parse_report.get('account_no')} ไม่ตรงกับข้อมูลธนาคาร (dStatement)",
            "detail": " · ".join(p for p in parts if p) + " — ตรวจว่าไฟล์ถูกแก้ไขหรือ OCR อ่านผิด ก่อนใช้ตัวเลขนี้",
            "amount": f"{amount:.2f}", "txn_ids": ids,
        })
    return out


def _evidence(db: Session, case: Case, r: AnalysisResult, rows: list[Transaction], period: tuple[date, date],
              alt_sync: dict | None) -> dict:
    """Alt-data haircut (E6-06), cash-pattern evidence (E4-06) and decision drivers (E7-06)."""
    uploaded = bills_svc.reconcile(db, case, rows, as_of=period[1])
    alt = altdata.evaluate(uploaded.bills, as_of=period[1])
    alt.signals += uploaded.signals
    months = r.months
    cfo_m = r.clean_cash_flow_monthly
    sizing_cfo = (cfo_m * (1 - alt.haircut)).quantize(Decimal("0.01"))

    withdrawals = [ETxn(t.id, t.account_id, t.posted_at, t.code or "", t.description, t.debit, t.credit)
                   for t in rows if r.outcomes[t.id].tag == "cash_withdrawal"]
    cash = cash_pattern.detect(withdrawals)

    _, drivers = explain(ExplainInputs(
        months=months, cfo_monthly=sizing_cfo, cfo_monthly_before_haircut=cfo_m,
        existing_debt_monthly=r.existing_debt_monthly, annual_rate=case.annual_rate,
        tenor_months=min(case.tenor_months, uploaded.tenor_cap_months or case.tenor_months),
        requested=case.requested_amount, tiers=r.tiers, household=r.costs["household"],
        pending_unverified=r.waterfall["unverified_pending"], loops=r.waterfall["own_account_loops"],
        owner_inflow=r.waterfall["owner_family_inflow"], haircut=alt.haircut,
        cash_pattern_detected=cash.detected, cash_total=cash.total, policy=policy_svc.current(db),
    ))
    wf, costs, tiers = r.waterfall, r.costs, r.tiers
    company = {a.id for a in db.scalars(select(Account).where(Account.case_id == case.id, Account.owner_type == "company"))}
    buyers = dict(db.execute(select(Invoice.id, Invoice.buyer_name).where(Invoice.case_id == case.id)).all())
    conc = concentration.analyze(
        [concentration.Receipt(t.id, t.posted_at, t.credit, buyers.get(r.outcomes[t.id].invoice_id) or t.counterparty_name)
         for t in rows if t.account_id in company and r.outcomes[t.id].tier in ("T1_golden", "T2_tax", "T3_operational")],
        months)
    found = anomalies.detect(
        [anomalies.ATxn(t.id, t.posted_at, t.debit, t.credit, r.outcomes[t.id].tag, r.outcomes[t.id].tier,
                        t.counterparty_name, t.account_id in company) for t in rows],
        period[1], months)
    return {
        "concentration": {
            "identified": f"{conc.identified:.2f}", "unidentified": f"{conc.unidentified:.2f}",
            "customers": conc.customers, "top1_share": str(conc.top1_share), "top5_share": str(conc.top5_share),
            "hhi": conc.hhi, "level": conc.level, "flags": conc.flags,
            "top": [{"name": c.name, "amount": f"{c.amount:.2f}", "share": str(c.share), "receipts": c.receipts,
                     "months_active": c.months_active, "txn_ids": c.txn_ids} for c in conc.top],
        },
        "anomalies": _bank_mismatches(db, case) + [
            {"kind": a.kind, "severity": a.severity, "title": a.title, "detail": a.detail,
             "amount": f"{a.amount:.2f}", "txn_ids": a.txn_ids} for a in found],
        "revenue_monthly": f"{wf['verified_operating_revenue'] / months:.2f}",
        "costs_monthly": f"{costs['business_operating'] / months:.2f}",
        "t1_monthly": f"{tiers['T1_golden'] / months:.2f}",
        "sizing_cfo_monthly": f"{sizing_cfo:.2f}",
        "alt_data": {
            "months_covered": alt.months_covered, "bills": alt.bills, "on_time": alt.on_time,
            "late_30": alt.late_30, "late_60_or_unpaid": alt.late_60_or_unpaid, "haircut": str(alt.haircut),
            "ews": alt.ews, "liveness_confirmed": alt.liveness_confirmed, "signals": alt.signals,
            "uploads": uploaded.counts,
            "lease_end": uploaded.lease_end.isoformat() if uploaded.lease_end else None,
            "tenor_cap_months": uploaded.tenor_cap_months,
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
