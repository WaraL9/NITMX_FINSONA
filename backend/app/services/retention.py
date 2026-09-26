"""Data deletion on request / end of retention (E14-08).

Deleting a case removes every stored file (statements, evidence, memos) and every row
derived from them. The audit log is kept — it records that the case existed, who deleted
it, why, and the fingerprints of the files removed — because the log itself is the
evidence that deletion happened. Audit rows reference cases by plain id, so nothing in
the chain is rewritten.
"""

from __future__ import annotations

import shutil

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Case, Document, Evidence, Transaction
from app.services import audit


def delete_case(db: Session, case_id: int, user_id: int, reason: str, ip: str | None) -> dict:
    case = db.get(Case, case_id)
    if case is None:
        raise LookupError("case not found")
    docs = db.query(Document).filter(Document.case_id == case_id).all()
    summary = {
        "company_name": case.company_name,
        "documents": [{"filename": d.filename, "sha256": d.sha256} for d in docs],
        "evidence_files": db.query(Evidence).filter(Evidence.case_id == case_id).count(),
        "transactions": db.query(Transaction).filter(Transaction.case_id == case_id).count(),
    }
    audit.log(db, "case_deleted", case_id=case_id, user_id=user_id, ip=ip, target_type="case", target_id=case_id,
              before=summary, reason=reason)
    db.delete(case)  # rows cascade via foreign keys
    db.commit()
    folder = settings.storage_dir / f"case_{case_id}"
    if folder.exists():
        shutil.rmtree(folder)
    return summary
