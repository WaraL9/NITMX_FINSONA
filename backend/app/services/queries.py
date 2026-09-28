"""Pinpoint queries and evidence (E12-04, E12-05, E13-06, E10-05).

A CA's "Query RM" on a Watchlist item creates one question tied to that exact
transaction — no blanket document requests. The RM answers with photos (contract,
delivery note, site photo) or forwards it to the SME, who answers from the portal.
Evidence files are validated by content, fingerprinted with SHA-256 and audit-logged.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.config import settings
from app.models import Case, Evidence, Query, Transaction, User, WatchlistItem
from app.services import audit
from app.core.i18n import th

MAX_FILE = 10 * 1024 * 1024
MAX_FILES = 5
# Detected from the bytes, never trusted from the client.
SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"%PDF-", "application/pdf", ".pdf"),
]


class QueryError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass
class Upload:
    filename: str
    data: bytes


def sniff(data: bytes) -> tuple[str, str] | None:
    for magic, mime, ext in SIGNATURES:
        if data.startswith(magic):
            return mime, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def create_from_watchlist(db: Session, item: WatchlistItem, user: User, question: str) -> Query:
    q = Query(case_id=item.case_id, transaction_id=item.transaction_id, watchlist_item_id=item.id, audience="rm",
              question=question.strip(), created_by=user.id)
    db.add(q)
    db.flush()
    return q


def _check_answerer(db: Session, q: Query, user: User) -> Case:
    case = db.get(Case, q.case_id)
    if user.role == "RM" and case.rm_user_id in (None, user.id):
        return case
    if user.role == "SME" and q.audience == "sme" and case.owner_user_id == user.id:
        return case
    raise QueryError("you cannot answer this question", 403)


def forward_to_sme(db: Session, q: Query, user: User, note: str | None, ip: str | None) -> Query:
    case = db.get(Case, q.case_id)
    if user.role != "RM" or case.rm_user_id not in (None, user.id):
        raise QueryError("only the case's RM can forward a question", 403)
    if q.status != "open":
        raise QueryError("question is not open", 409)
    q.audience = "sme"
    if note:
        q.question = th(f"{q.question}\n\nจาก RM: {note.strip()}")
    audit.log(db, "query_forwarded", case_id=q.case_id, user_id=user.id, ip=ip, target_type="query",
              target_id=q.id, after={"audience": "sme"})
    db.commit()
    return q


def answer(db: Session, q: Query, user: User, note: str, files: list[Upload], ip: str | None) -> Query:
    case = _check_answerer(db, q, user)
    if q.status != "open":
        raise QueryError("question already answered", 409)
    if not note.strip() and not files:
        raise QueryError("add a note or at least one photo")
    if len(files) > MAX_FILES:
        raise QueryError(f"at most {MAX_FILES} files")
    folder = settings.storage_dir / f"case_{case.id}" / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    stored = []
    for f in files:
        if not f.data or len(f.data) > MAX_FILE:
            raise QueryError(f"{f.filename}: empty or larger than 10 MB")
        kind = sniff(f.data)
        if kind is None:
            raise QueryError(f"{f.filename}: only JPEG, PNG, WEBP or PDF")
        mime, ext = kind
        digest = hashlib.sha256(f.data).hexdigest()
        path = folder / f"{digest}{ext}"
        storage.write(path, f.data)
        ev = Evidence(case_id=case.id, query_id=q.id, transaction_id=q.transaction_id, filename=f.filename[:255],
                      mime=mime, size=len(f.data), sha256=digest, storage_path=str(path), uploaded_by=user.id)
        db.add(ev)
        stored.append({"filename": ev.filename, "sha256": digest, "mime": mime})
    q.status, q.answer_note, q.answered_by = "answered", note.strip() or None, user.id
    q.answered_at = datetime.now(timezone.utc)
    audit.log(db, "query_answered", case_id=case.id, user_id=user.id, ip=ip, target_type="query", target_id=q.id,
              after={"audience": q.audience, "files": stored}, reason=q.answer_note)
    db.commit()
    db.refresh(q)
    return q


def serialize(db: Session, q: Query) -> dict:
    names = {u.id: u.name for u in db.scalars(select(User))}
    t = db.get(Transaction, q.transaction_id)
    ev = db.scalars(select(Evidence).where(Evidence.query_id == q.id).order_by(Evidence.id)).all()
    return {
        "id": q.id, "case_id": q.case_id, "transaction_id": q.transaction_id, "watchlist_item_id": q.watchlist_item_id,
        "audience": q.audience, "question": q.question, "status": q.status,
        "created_by": names.get(q.created_by), "created_at": q.created_at,
        "answer_note": q.answer_note, "answered_by": names.get(q.answered_by), "answered_at": q.answered_at,
        "amount": f"{t.credit if t.credit else t.debit:.2f}", "txn_date": t.posted_at.date().isoformat(),
        "counterparty": t.counterparty_name, "description": t.description,
        "evidence": [{"id": e.id, "filename": e.filename, "mime": e.mime, "size": e.size, "sha256": e.sha256,
                      "uploaded_by": names.get(e.uploaded_by), "uploaded_at": e.uploaded_at} for e in ev],
    }
