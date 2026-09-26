"""Purpose-bound consent registry (E13-03, E14-02).

Each external data source needs its own consent. The latest record per purpose wins, so a
revocation is just a newer record with granted=False; history is kept. Every change is
audit-logged.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Consent
from app.services import audit

PURPOSES = {
    "credit_assessment": "ใช้ข้อมูลเพื่อพิจารณาสินเชื่อ",
    "promptbiz_data": "ดึงข้อมูลใบแจ้งหนี้และการชำระเงินจากโครงข่าย PromptBiz",
    "utility_data": "ดึงประวัติการชำระค่าไฟฟ้า ค่าน้ำ และค่าเช่า",
}
VERSION = "v1"


def current(db: Session, case_id: int) -> dict[str, Consent | None]:
    rows = db.scalars(select(Consent).where(Consent.case_id == case_id).order_by(Consent.id))
    latest: dict[str, Consent | None] = {p: None for p in PURPOSES}
    for c in rows:
        latest[c.purpose] = c
    return latest


def has(db: Session, case_id: int, purpose: str) -> Consent | None:
    c = current(db, case_id).get(purpose)
    return c if c is not None and c.granted else None


def record(db: Session, case_id: int, grants: dict[str, bool], user_id: int | None, ip: str | None = None) -> None:
    before = {p: (c.granted if c else None) for p, c in current(db, case_id).items()}
    for purpose, granted in grants.items():
        if purpose not in PURPOSES:
            raise ValueError(f"unknown consent purpose {purpose!r}")
        if before.get(purpose) == granted:
            continue
        db.add(Consent(case_id=case_id, purpose=purpose, granted=granted, version=VERSION, recorded_by=user_id))
    db.flush()
    after = {p: (c.granted if c else None) for p, c in current(db, case_id).items()}
    if after != before:
        audit.log(db, "consent_change", case_id=case_id, user_id=user_id, ip=ip, target_type="case",
                  target_id=case_id, before=before, after={**after, "version": VERSION})
