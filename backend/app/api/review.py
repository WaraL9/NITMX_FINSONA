"""Human-in-the-loop review (E9-02..E9-07) and pixel lineage (E10-01..E10-04).

Every change a CA makes is (1) validated server-side, (2) written to the hash-chained
audit log with before/after and the CA's reason, and (3) followed by a re-run of the
engine, so the response already carries the updated numbers.
"""

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.api.analysis import _out as analysis_out
from app.api.common import txn_out
from app.api.deps import client_ip, current_user, require_role
from app.db import get_db
from app.engine.types import CREDIT_OVERRIDES, DEBIT_OVERRIDES
from app.models import (Account, AltDataRecord, AuditEntry, Document, Page, TagOverride, Transaction, User,
                        WatchlistItem)
from app.schemas import (
    AnalysisOut,
    AuditEntryOut,
    BillReviewIn,
    ChainStatusOut,
    DecisionIn,
    DecisionOut,
    DocumentOut,
    DocumentVerifyOut,
    LineageOut,
    OcrReviewIn,
    OcrReviewOut,
    OverrideIn,
    OverrideOut,
    ReasonIn,
    TransactionOut,
    WatchlistOut,
)
from app.services import audit, ocr_review
from app.services.analysis import AnalysisError, run_analysis

router = APIRouter(tags=["review"])

# action -> (allowed from statuses, resulting status)
TRANSITIONS = {
    "accept": ({"pending", "queried"}, "accepted"),
    "exclude": ({"pending", "queried"}, "excluded"),
    "query_rm": ({"pending"}, "queried"),
    "reopen": ({"accepted", "excluded", "queried"}, "pending"),
}


def _page_no(db: Session, t: Transaction) -> int | None:
    return db.scalar(select(Page.page_no).where(Page.id == t.page_id)) if t.page_id else None


def _rerun(db: Session, case_id: int, user: User, request: Request, trigger: str):
    try:
        return run_analysis(db, case_id, sync_invoices=False, user_id=user.id, ip=client_ip(request), trigger=trigger)
    except AnalysisError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e


@router.post("/api/cases/{case_id}/bills/{record_id}/review", response_model=AnalysisOut)
def review_bill(case_id: int, record_id: int, body: BillReviewIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_role("CA"))):
    """E2-14: a CA checks an OCR'd bill against its image — confirm as read, or correct the
    amount/dates. Audit-logged with before/after and the reason; the engine re-runs."""
    r = db.get(AltDataRecord, record_id)
    if r is None or r.case_id != case_id or r.source != "bill_upload":
        raise HTTPException(404, "bill not found")
    before = {"amount": f"{r.amount:.2f}", "due_date": r.due_date.isoformat(),
              "paid_date": r.paid_date.isoformat() if r.paid_date else None, "review_status": r.review_status}
    if body.action == "correct":
        if body.amount is None and body.due_date is None and body.paid_date is None:
            raise HTTPException(422, "a correction needs at least one of amount, due_date, paid_date")
        r.amount = body.amount if body.amount is not None else r.amount
        r.due_date = body.due_date or r.due_date
        r.paid_date = body.paid_date or r.paid_date
    r.review_status = "corrected" if body.action == "correct" else "confirmed"
    audit.log(db, "bill_review", case_id=case_id, user_id=user.id, ip=client_ip(request), target_type="alt_data",
              target_id=r.id, before=before, reason=body.reason.strip(), after={
                  "action": body.action, "amount": f"{r.amount:.2f}", "due_date": r.due_date.isoformat(),
                  "paid_date": r.paid_date.isoformat() if r.paid_date else None, "review_status": r.review_status})
    db.flush()
    return analysis_out(_rerun(db, case_id, user, request, trigger="bill_review"))


@router.post("/api/cases/{case_id}/watchlist/{item_id}/decision", response_model=DecisionOut)
def decide(case_id: int, item_id: int, body: DecisionIn, request: Request, db: Session = Depends(get_db),
           user: User = Depends(require_role("CA"))):
    item = db.get(WatchlistItem, item_id)
    if item is None or item.case_id != case_id:
        raise HTTPException(404, "watchlist item not found")
    allowed, new_status = TRANSITIONS[body.action]
    if item.status not in allowed:
        raise HTTPException(409, f"cannot {body.action} an item that is {item.status}")
    before = {"status": item.status, "reason": item.reason}
    item.status = new_status
    item.reason = body.reason.strip()
    item.decided_by = user.id
    item.decided_at = datetime.now(timezone.utc)
    t = db.get(Transaction, item.transaction_id)
    if body.action == "query_rm":
        from app.services import queries as qsvc

        qsvc.create_from_watchlist(db, item, user, item.reason)
    audit.log(db, "watchlist_decision", case_id=case_id, user_id=user.id, ip=client_ip(request),
              target_type="transaction", target_id=t.id, before=before,
              after={"status": new_status, "amount": f"{t.credit:.2f}", "date": t.posted_at.date().isoformat()},
              reason=item.reason)
    analysis = _rerun(db, case_id, user, request, f"watchlist_{body.action}")
    db.refresh(item)
    t = db.get(Transaction, item.transaction_id)
    return DecisionOut(
        item=WatchlistOut(id=item.id, status=item.status, suspicion_score=item.suspicion_score,
                          system_note=item.system_note, reason=item.reason, transaction=txn_out(t, _page_no(db, t)),
                          evidence_hint=item.evidence_hint),
        analysis=analysis_out(analysis),
    )


def _override_target(db: Session, case_id: int, txn_id: int) -> tuple[Transaction, Account]:
    t = db.get(Transaction, txn_id)
    if t is None or t.case_id != case_id:
        raise HTTPException(404, "transaction not found")
    acct = db.get(Account, t.account_id)
    if acct.owner_type != "company":
        raise HTTPException(422, "only company-account transactions affect revenue and costs")
    if db.scalar(select(WatchlistItem).where(WatchlistItem.transaction_id == txn_id)):
        raise HTTPException(422, "this transaction is on the Watchlist — use Accept/Exclude there")
    return t, acct


@router.put("/api/cases/{case_id}/transactions/{txn_id}/override", response_model=OverrideOut)
def set_override(case_id: int, txn_id: int, body: OverrideIn, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_role("CA"))):
    t, _ = _override_target(db, case_id, txn_id)
    valid = CREDIT_OVERRIDES if t.credit > 0 else DEBIT_OVERRIDES
    if body.value not in valid:
        raise HTTPException(422, f"for this transaction the override must be one of {', '.join(valid)}")
    o = db.scalar(select(TagOverride).where(TagOverride.transaction_id == txn_id))
    before = {"tag": t.tag, "tier": t.tier, "override": o.value if o else None}
    if o is None:
        o = TagOverride(case_id=case_id, transaction_id=txn_id, value=body.value, reason=body.reason, user_id=user.id)
        db.add(o)
    else:
        o.value, o.reason, o.user_id = body.value, body.reason, user.id
    audit.log(db, "tag_override", case_id=case_id, user_id=user.id, ip=client_ip(request), target_type="transaction",
              target_id=txn_id, before=before, after={"override": body.value}, reason=body.reason)
    analysis = _rerun(db, case_id, user, request, "tag_override")
    db.refresh(t)
    return OverrideOut(transaction=txn_out(t, _page_no(db, t)), analysis=analysis_out(analysis))


@router.post("/api/cases/{case_id}/transactions/{txn_id}/override/revert", response_model=OverrideOut)
def revert_override(case_id: int, txn_id: int, body: ReasonIn, request: Request,
                    db: Session = Depends(get_db), user: User = Depends(require_role("CA"))):
    t, _ = _override_target(db, case_id, txn_id)
    o = db.scalar(select(TagOverride).where(TagOverride.transaction_id == txn_id))
    if o is None:
        raise HTTPException(404, "no override on this transaction")
    audit.log(db, "tag_override_revert", case_id=case_id, user_id=user.id, ip=client_ip(request),
              target_type="transaction", target_id=txn_id, before={"override": o.value}, after={"override": None},
              reason=body.reason)
    db.delete(o)
    analysis = _rerun(db, case_id, user, request, "tag_override_revert")
    db.refresh(t)
    return OverrideOut(transaction=txn_out(t, _page_no(db, t)), analysis=analysis_out(analysis))


@router.get("/api/cases/{case_id}/ocr-review", response_model=list[TransactionOut])
def ocr_review_queue(case_id: int, status: str = Query("all", pattern="^(all|pending)$"), db: Session = Depends(get_db)):
    """E2-09: OCR rows that needed (or still need) a human look, in document order."""
    q = select(Transaction).where(Transaction.case_id == case_id, Transaction.review_status.is_not(None))
    if status == "pending":
        q = q.where(Transaction.review_status == ocr_review.PENDING)
    rows = db.scalars(q.order_by(Transaction.document_id, Transaction.row_index)).all()
    pages = dict(db.execute(select(Page.id, Page.page_no).where(Page.id.in_({t.page_id for t in rows if t.page_id}))).all())
    return [txn_out(t, pages.get(t.page_id)) for t in rows]


@router.post("/api/cases/{case_id}/ocr-review/{txn_id}", response_model=OcrReviewOut)
def ocr_review_resolve(case_id: int, txn_id: int, body: OcrReviewIn, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(require_role("CA"))):
    """E2-10: confirm or correct an OCR reading; re-checks balances and re-runs the engine."""
    values = {k: getattr(body, k) for k in ("debit", "credit", "balance")} if body.action == "correct" else None
    try:
        res = ocr_review.resolve(db, case_id, txn_id, body.action, user.id, body.reason, values, client_ip(request))
    except ocr_review.ReviewError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    a = _rerun(db, case_id, user, request, trigger="ocr_review")
    return OcrReviewOut(txn=txn_out(res.txn, _page_no(db, res.txn)), changed=res.changed,
                        pending_left=res.pending_left, analysis=analysis_out(a))


@router.get("/api/cases/{case_id}/audit", response_model=list[AuditEntryOut])
def case_audit(case_id: int, db: Session = Depends(get_db)):
    names = {u.id: u.name for u in db.scalars(select(User))}
    rows = db.scalars(select(AuditEntry).where(AuditEntry.case_id == case_id).order_by(AuditEntry.id.desc()))
    return [AuditEntryOut.model_validate(e).model_copy(update={"user_name": names.get(e.user_id)}) for e in rows]


def _audit_rows(db: Session, action: str | None, user_id: int | None, case_id: int | None, limit: int):
    q = select(AuditEntry).order_by(AuditEntry.id.desc())
    if action:
        q = q.where(AuditEntry.action == action)
    if user_id:
        q = q.where(AuditEntry.user_id == user_id)
    if case_id:
        q = q.where(AuditEntry.case_id == case_id)
    return db.scalars(q.limit(limit)).all()


@router.get("/api/audit", response_model=list[AuditEntryOut])
def audit_log(action: str | None = None, user_id: int | None = None, case_id: int | None = None,
              limit: int = Query(200, ge=1, le=5000), db: Session = Depends(get_db),
              _: User = Depends(require_role("CA", "AUDITOR"))):
    """E9-07: the whole chain (including deleted cases), filterable."""
    names = {u.id: u.name for u in db.scalars(select(User))}
    return [AuditEntryOut.model_validate(e).model_copy(update={"user_name": names.get(e.user_id)})
            for e in _audit_rows(db, action, user_id, case_id, limit)]


@router.get("/api/audit.csv", response_class=Response)
def audit_csv(action: str | None = None, user_id: int | None = None, case_id: int | None = None,
              db: Session = Depends(get_db), _: User = Depends(require_role("CA", "AUDITOR"))):
    """E9-07: CSV export for Internal Audit / BOT, with the hashes so the chain can be re-checked offline."""
    import csv
    import io
    import json as _json

    names = {u.id: u.name for u in db.scalars(select(User))}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "ts_utc", "case_id", "user", "ip", "action", "target_type", "target_id", "reason",
                "before", "after", "prev_hash", "hash"])
    for e in reversed(_audit_rows(db, action, user_id, case_id, 100_000)):
        w.writerow([e.id, e.ts.isoformat(), e.case_id, names.get(e.user_id, "system"), e.ip, e.action,
                    e.target_type, e.target_id, e.reason,
                    _json.dumps(e.before, ensure_ascii=False) if e.before else "",
                    _json.dumps(e.after, ensure_ascii=False) if e.after else "", e.prev_hash, e.hash])
    # BOM so Excel opens Thai text correctly.
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="finsona_audit_log.csv"'})


@router.get("/api/audit/verify", response_model=ChainStatusOut)
def verify_audit(db: Session = Depends(get_db)):
    s = audit.verify(db)
    return ChainStatusOut(ok=s.ok, entries=s.entries, first_bad_id=s.first_bad_id, detail=s.detail)


def _sha_ok(doc: Document) -> tuple[str, bool]:
    path = Path(doc.storage_path)
    if not path.exists():
        return "", False
    try:
        current = hashlib.sha256(storage.read(path)).hexdigest()
    except storage.StorageCorrupt:
        return "", False
    return current, current == doc.sha256


@router.get("/api/documents/{document_id}/verify", response_model=DocumentVerifyOut)
def verify_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    current, ok = _sha_ok(doc)
    return DocumentVerifyOut(document_id=doc.id, filename=doc.filename, recorded_sha256=doc.sha256,
                             current_sha256=current, verified=ok)


@router.get("/api/transactions/{txn_id}/lineage", response_model=LineageOut)
def lineage(txn_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Everything needed to show a transaction on its source page; the view itself is audit-logged."""
    t = db.get(Transaction, txn_id)
    if t is None:
        raise HTTPException(404, "transaction not found")
    doc = db.get(Document, t.document_id) if t.document_id else None
    page = db.get(Page, t.page_id) if t.page_id else None
    ok = _sha_ok(doc)[1] if doc else None
    audit.log(db, "lineage_view", case_id=t.case_id, user_id=user.id, ip=client_ip(request),
              target_type="transaction", target_id=t.id,
              after={"document_id": doc.id if doc else None, "page": page.page_no if page else None,
                     "sha256_verified": ok})
    db.commit()
    return LineageOut(
        transaction=txn_out(t, page.page_no if page else None),
        document=DocumentOut.model_validate(doc) if doc else None,
        page_width=page.width if page else None,
        page_height=page.height if page else None,
        sha256_verified=ok,
    )
