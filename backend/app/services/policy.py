"""Credit policy configuration (E6-08).

The bank's thresholds live in the database, not in code. Each change adds a new version
(history is kept), is audit-logged with before/after and the reason, and re-runs the
analysis of open cases so every screen reflects the new policy immediately. Signed memos
keep the numbers they were signed with (their PDF is immutable).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.types import Policy
from app.models import Analysis, Case, CreditPolicy
from app.services import audit

BOUNDS = {
    "min_dscr": (Decimal("1.00"), Decimal("3.00")),
    "target_dscr": (Decimal("1.00"), Decimal("3.00")),
    "max_dsr": (Decimal("0.30"), Decimal("1.00")),
    "trade_line_ratio": (Decimal("0.00"), Decimal("1.00")),
}


class PolicyError(ValueError):
    pass


def latest(db: Session) -> CreditPolicy | None:
    return db.scalar(select(CreditPolicy).order_by(CreditPolicy.id.desc()).limit(1))


def current(db: Session) -> Policy:
    row = latest(db)
    if row is None:
        return Policy()
    return Policy(min_dscr=row.min_dscr, target_dscr=row.target_dscr, max_dsr=row.max_dsr,
                  trade_line_ratio=row.trade_line_ratio)


def as_dict(p: Policy) -> dict[str, str]:
    return {k: str(getattr(p, k)) for k in BOUNDS}


def update(db: Session, values: dict[str, Decimal], user_id: int, reason: str, ip: str | None) -> Policy:
    before = current(db)
    merged = {k: values.get(k, getattr(before, k)) for k in BOUNDS}
    for k, (lo, hi) in BOUNDS.items():
        if not (lo <= merged[k] <= hi):
            raise PolicyError(f"{k} must be between {lo} and {hi}")
    if merged["target_dscr"] < merged["min_dscr"]:
        raise PolicyError("target DSCR must be at least the minimum DSCR")
    db.add(CreditPolicy(**merged, updated_by=user_id, reason=reason))
    db.flush()
    after = current(db)
    audit.log(db, "policy_change", user_id=user_id, ip=ip, target_type="policy", target_id="credit",
              before=as_dict(before), after=as_dict(after), reason=reason)
    db.commit()

    # Refresh open cases so their sizing, drivers and memo drafts use the new thresholds.
    from app.services.analysis import run_analysis

    analysed = {a.case_id for a in db.scalars(select(Analysis))}
    for case in db.scalars(select(Case).where(Case.id.in_(analysed), Case.status != "decided")).all():
        run_analysis(db, case.id, sync_invoices=False, user_id=user_id, ip=ip, trigger="policy_change")
    return after
