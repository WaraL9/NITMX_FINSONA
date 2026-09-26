"""Append-only, hash-chained audit log (E9-05, E9-06).

Each entry stores prev_hash and hash = SHA-256 of the entry's canonical JSON (which
includes prev_hash). Changing or deleting any past entry breaks every hash after it, and
verify() reports the first entry where the chain no longer holds.

One global chain covers every case, so entries can't be dropped from one case unnoticed.
Appends take the write lock (insert) before reading the chain head, inside the caller's
transaction; SQLite serialises writers, which is enough for this single-node deployment.
A server database would need an explicit lock (e.g. SELECT ... FOR UPDATE on a head row).
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEntry

GENESIS = "0" * 64


def _canonical(e: AuditEntry) -> str:
    return json.dumps(
        {
            "case_id": e.case_id,
            "ts": e.ts.isoformat(),
            "user_id": e.user_id,
            "ip": e.ip,
            "action": e.action,
            "target_type": e.target_type,
            "target_id": e.target_id,
            "before": e.before,
            "after": e.after,
            "reason": e.reason,
            "prev_hash": e.prev_hash,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def _digest(e: AuditEntry) -> str:
    return hashlib.sha256(_canonical(e).encode("utf-8")).hexdigest()


def _jsonable(d: dict[str, Any] | None) -> dict[str, Any] | None:
    # Round-trip through JSON now so what we hash is exactly what the DB returns later.
    return None if d is None else json.loads(json.dumps(d, ensure_ascii=False, default=str))


def log(
    db: Session,
    action: str,
    *,
    case_id: int | None = None,
    user_id: int | None = None,
    ip: str | None = None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditEntry:
    """Append an entry. Flushes but does not commit — it lands with the caller's transaction.

    The row is inserted *before* the chain head is read: the insert takes SQLite's write
    lock, so no other transaction can commit an entry between reading the head and our
    commit. Reading the head first let two concurrent requests link to the same parent
    and fork the chain (found by the E16-03 browser smoke test).
    """
    e = AuditEntry(
        case_id=case_id,
        ts=datetime.now(timezone.utc).replace(tzinfo=None),
        user_id=user_id,
        ip=ip,
        action=action,
        target_type=target_type,
        target_id=None if target_id is None else str(target_id),
        before=_jsonable(before),
        after=_jsonable(after),
        reason=reason,
        prev_hash=GENESIS,
        hash=secrets.token_hex(32),  # unique placeholder until linked below
    )
    db.add(e)
    db.flush()
    last = db.scalar(select(AuditEntry).where(AuditEntry.id < e.id).order_by(AuditEntry.id.desc()).limit(1))
    e.prev_hash = last.hash if last else GENESIS
    e.hash = _digest(e)
    db.flush()
    return e


@dataclass
class ChainStatus:
    ok: bool
    entries: int
    first_bad_id: int | None
    detail: str | None


def verify(db: Session) -> ChainStatus:
    prev = GENESIS
    n = 0
    for e in db.scalars(select(AuditEntry).order_by(AuditEntry.id)):
        n += 1
        if e.prev_hash != prev:
            return ChainStatus(False, n, e.id, "prev_hash does not match the previous entry (entry removed or reordered)")
        if _digest(e) != e.hash:
            return ChainStatus(False, n, e.id, "entry content does not match its hash (entry modified)")
        prev = e.hash
    return ChainStatus(True, n, None, None)
