"""Human-in-the-loop review (E9-02..E9-07) and pixel lineage (E10-01..E10-04).

Every change a CA makes is (1) validated server-side, (2) written to the hash-chained
audit log with before/after and the CA's reason, and (3) followed by a re-run of the
engine, so the response already carries the updated numbers.
"""

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.analysis import _out as analysis_out
from app.api.common import txn_out
from app.api.deps import client_ip, current_user, require_role
from app.db import get_db
from app.engine.types import CREDIT_OVERRIDES, DEBIT_OVERRIDES
from app.models import Account, AuditEntry, Document, Page, TagOverride, Transaction, User, WatchlistItem
from app.schemas import (
    AuditEntryOut,
    ChainStatusOut,
    DecisionIn,
    DecisionOut,
    DocumentOut,
    DocumentVerifyOut,
    LineageOut,
    OverrideIn,
    OverrideOut,
    ReasonIn,
    UserOut,
    WatchlistOut,
)
from app.services import audit
from app.services.analysis import AnalysisError, run_analysis

router = APIRouter(tags=["review"])

# action -> (allowed from statuses, resulting status)
TRANSITIONS = {
    "accept": ({"pending", "queried"}, "accepted"),
    "exclude": ({"pending", "queried"}, "excluded"),
    "query_rm": ({"pending"}, "queried"),
    "reopen": ({"accepted", "excluded", "queried"}, "pending"),
}


@router.get("/api/users", response_model=list[UserOut])
def users(db: Session = Depends(get_db)):
    return list(db.scalars(select(User).order_by(User.id)))


@router.get("/api/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


def _page_no(db: Session, t: Transaction) -> int | None:
    return db.scalar(select(Page.page_no).where(Page.id == t.page_id)) if t.page_id else None


def _rerun(db: Session, case_id: int, user: User, request: Request, trigger: str):
    try:
        return run_analysis(db, case_id, sync_invoices=False, user_id=user.id, ip=client_ip(request), trigger=trigger)
    except AnalysisError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e


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
                          system_note=item.system_note, reason=item.reason, transaction=txn_out(t, _page_no(db, t))),
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


@router.get("/api/cases/{case_id}/audit", response_model=list[AuditEntryOut])
def case_audit(case_id: int, db: Session = Depends(get_db)):
    names = {u.id: u.name for u in db.scalars(select(User))}
    rows = db.scalars(select(AuditEntry).where(AuditEntry.case_id == case_id).order_by(AuditEntry.id.desc()))
    return [AuditEntryOut.model_validate(e).model_copy(update={"user_name": names.get(e.user_id)}) for e in rows]


@router.get("/api/audit/verify", response_model=ChainStatusOut)
def verify_audit(db: Session = Depends(get_db)):
    s = audit.verify(db)
    return ChainStatusOut(ok=s.ok, entries=s.entries, first_bad_id=s.first_bad_id, detail=s.detail)


def _sha_ok(doc: Document) -> tuple[str, bool]:
    path = Path(doc.storage_path)
    if not path.exists():
        return "", False
    current = hashlib.sha256(path.read_bytes()).hexdigest()
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
