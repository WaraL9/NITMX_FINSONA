"""Credit memo evidence appendix (E11-05): what an auditor needs to re-perform the decision.

Page 1 of the memo is the decision; the appendix lists the evidence behind it — every
source file with its fingerprint, statement coverage, external data used, every CA
judgement with its reason, risk observations, and the audit-chain position the memo was
signed at. Everything here is read from the database; nothing is recomputed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (AltDataRecord, AuditEntry, Case, Document, Invoice, TagOverride, TaxFiling, Transaction, User,
                        WatchlistItem)
from app.services import coverage


def build(db: Session, case: Case, analysis: dict[str, Any]) -> dict[str, Any]:
    names = {u.id: u.name for u in db.scalars(select(User))}
    docs = []
    for d in db.scalars(select(Document).where(Document.case_id == case.id).order_by(Document.uploaded_at)):
        r = d.parse_report or {}
        docs.append({
            "filename": d.filename, "kind": d.kind, "pages": d.page_count, "sha256": d.sha256,
            "rows": r.get("rows"), "parser": d.parser or "", "continuity_ok": r.get("continuity_ok"),
            "ocr_confidence": (r.get("ocr") or {}).get("mean_confidence"),
            "period": r.get("period") or (f"{r['period_start']} – {r['period_end']}" if r.get("period_start") else None),
        })
    inv_total, inv_n = db.execute(select(func.coalesce(func.sum(Invoice.amount), 0), func.count())
                                  .where(Invoice.case_id == case.id)).one()
    matched = db.scalar(select(func.count()).select_from(Transaction)
                        .where(Transaction.case_id == case.id, Transaction.invoice_id.is_not(None))) or 0
    filings = [{"period": f.period, "sales": f"{f.sales:.2f}"}
               for f in db.scalars(select(TaxFiling).where(TaxFiling.case_id == case.id).order_by(TaxFiling.period))]
    bills = db.scalar(select(func.count()).select_from(AltDataRecord).where(AltDataRecord.case_id == case.id)) or 0

    judgements = []
    for w, t in db.execute(select(WatchlistItem, Transaction).join(Transaction, Transaction.id == WatchlistItem.transaction_id)
                           .where(WatchlistItem.case_id == case.id, WatchlistItem.status != "pending")
                           .order_by(Transaction.posted_at)).all():
        judgements.append({"kind": "watchlist", "date": t.posted_at.date().isoformat(), "what": t.counterparty_name or t.description,
                           "amount": f"{t.credit:.2f}", "decision": w.status, "reason": w.reason, "by": names.get(w.decided_by)})
    for o, t in db.execute(select(TagOverride, Transaction).join(Transaction, Transaction.id == TagOverride.transaction_id)
                           .where(TagOverride.case_id == case.id)).all():
        judgements.append({"kind": "override", "date": t.posted_at.date().isoformat(), "what": t.counterparty_name or t.description,
                           "amount": f"{(t.credit or t.debit):.2f}", "decision": o.value, "reason": o.reason, "by": names.get(o.user_id)})
    ocr = dict(db.execute(select(Transaction.review_status, func.count()).where(Transaction.case_id == case.id,
                                                                                 Transaction.review_status.is_not(None))
                          .group_by(Transaction.review_status)).all())
    chain_n = db.scalar(select(func.count()).select_from(AuditEntry)) or 0
    conc = analysis.get("concentration") or {}
    return {
        "documents": docs,
        "coverage": coverage.compute(db, case),
        "external": {"invoices": inv_n, "invoice_total": f"{Decimal(inv_total):.2f}", "receipts_matched": matched,
                     "tax_filings": filings, "utility_bills": bills,
                     "connector": (analysis.get("connector") or {}).get("source")},
        "judgements": judgements,
        "ocr_review": {k: v for k, v in ocr.items()},
        "concentration": {k: conc.get(k) for k in ("level", "customers", "top1_share", "top5_share", "hhi", "flags")},
        "anomalies": [{"title": a["title"], "detail": a["detail"]} for a in analysis.get("anomalies") or []],
        "audit_entries": chain_n,
        "engine_version": analysis.get("engine_version"),
        "analysis_id": analysis.get("id"),
    }
