"""OCR human review queue (E2-09, E2-10).

A row read by OCR goes to review when
  * any key field (date, time, debit, credit, balance) was read below the confidence
    threshold (default 0.5), or
  * the running balance breaks at that row and no low-confidence read next to it
    explains the break — i.e. OCR was confidently wrong somewhere.

The CA confirms the reading or corrects the figures while looking at the highlighted
row on the scan. Every action is audit-logged with before/after, the balance chain is
re-checked (one correction can clear the breaks it caused) and the case is re-analysed.
Signing the memo is blocked while anything is still pending (see memo.sign).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Document, Transaction
from app.services import audit

KEY_FIELDS = ("date", "time", "debit", "credit", "balance")
PENDING = "pending"


class ReviewError(ValueError):
    pass


def _rows(db: Session, document_id: int) -> list[Transaction]:
    return list(db.scalars(select(Transaction).where(Transaction.document_id == document_id)
                           .order_by(Transaction.row_index)))


def balance_breaks(rows: list[Transaction], opening: Decimal | None) -> set[int]:
    """Transaction ids where previous balance - debit + credit != printed balance."""
    out: set[int] = set()
    prev = opening
    for t in rows:
        if prev is not None and t.balance is not None and prev - t.debit + t.credit != t.balance:
            out.add(t.id)
        prev = t.balance
    return out


def flag_document(db: Session, doc: Document) -> int:
    """(Re)compute review flags for an OCR document. Returns the number of pending rows.

    Rows a CA already confirmed or corrected keep their status; only the reasons are
    refreshed so the queue shows why a row was looked at.
    """
    rows = _rows(db, doc.id)
    opening = (doc.parse_report or {}).get("opening_balance")
    breaks = balance_breaks(rows, Decimal(opening) if opening else None)
    threshold = settings.ocr_review_threshold
    low = {t.id for t in rows if t.review_status is None or t.review_status == PENDING
           if any(c < threshold for c in (t.ocr_fields or {}).values())}
    # A break at row i means row i's amount or balance, or row i-1's balance, is wrong. A
    # low-confidence read at i or i-1 explains it; otherwise OCR was confidently wrong, so
    # both rows go to review — the culprit is one of them.
    unexplained: set[int] = set()
    for i, t in enumerate(rows):
        if t.id in breaks:
            pair = {t.id} | ({rows[i - 1].id} if i else set())
            if not (pair & low):
                unexplained |= pair
    pending = 0
    for t in rows:
        reasons = sorted(f"low_confidence:{f}" for f, c in (t.ocr_fields or {}).items() if c < threshold)
        if t.id in unexplained:
            reasons.append("balance_break")
        if t.review_status in ("confirmed", "corrected"):
            t.review_reasons = reasons or t.review_reasons
            continue
        if reasons:
            t.review_status, t.review_reasons = PENDING, reasons
            pending += 1
        else:
            t.review_status, t.review_reasons = None, None
    report = dict(doc.parse_report or {})
    report["continuity_ok"] = not breaks
    report["continuity_breaks"] = sorted(t.row_index for t in rows if t.id in breaks)[:50]
    if "ocr" in report:
        report["ocr"] = {**report["ocr"], "review_pending": pending}
    doc.parse_report = report
    db.flush()
    return pending


AMOUNT_REASONS = {"low_confidence:debit", "low_confidence:credit", "balance_break"}
HELD_TAG = "ocr_pending"


def amount_uncertain(t: Transaction) -> bool:
    """Pending rows whose money figure itself is in doubt are held out of the math (E2-09).

    A row where only the date, time or printed balance was unclear still has a reliable
    amount, so it is used — but still needs review before the memo can be signed.
    """
    return t.review_status == PENDING and bool(AMOUNT_REASONS & set(t.review_reasons or ()))


def pending_count(db: Session, case_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Transaction)
                     .where(Transaction.case_id == case_id, Transaction.review_status == PENDING)) or 0


@dataclass
class Resolution:
    txn: Transaction
    changed: bool
    pending_left: int


def resolve(db: Session, case_id: int, txn_id: int, action: str, user_id: int, reason: str | None,
            values: dict[str, Decimal] | None = None, ip: str | None = None) -> Resolution:
    t = db.get(Transaction, txn_id)
    if t is None or t.case_id != case_id:
        raise ReviewError("transaction not found in this case")
    if t.ocr_fields is None:
        raise ReviewError("this row was not read by OCR")
    before = {"status": t.review_status, "debit": f"{t.debit:.2f}", "credit": f"{t.credit:.2f}",
              "balance": None if t.balance is None else f"{t.balance:.2f}"}
    changed = False
    if action == "confirm":
        t.review_status = "confirmed"
    elif action == "correct":
        values = {k: v for k, v in (values or {}).items() if v is not None}
        if not values:
            raise ReviewError("nothing to correct")
        if any(v < 0 for v in values.values()):
            raise ReviewError("amounts cannot be negative")
        if values.get("debit", t.debit) and values.get("credit", t.credit):
            raise ReviewError("a row has either a debit or a credit, not both")
        if not reason or len(reason.strip()) < 10:
            raise ReviewError("a correction needs a reason of at least 10 characters")
        for k, v in values.items():
            if getattr(t, k) != v:
                setattr(t, k, v)
                changed = True
        t.review_status = "corrected" if changed else "confirmed"
    else:
        raise ReviewError(f"unknown action {action!r}")
    after = {"status": t.review_status, "debit": f"{t.debit:.2f}", "credit": f"{t.credit:.2f}",
             "balance": None if t.balance is None else f"{t.balance:.2f}"}
    audit.log(db, "ocr_review", case_id=case_id, user_id=user_id, ip=ip, target_type="transaction",
              target_id=t.id, before=before, after=after, reason=reason)
    doc = db.get(Document, t.document_id) if t.document_id else None
    if doc is not None:
        flag_document(db, doc)
    return Resolution(t, changed, pending_count(db, case_id))
