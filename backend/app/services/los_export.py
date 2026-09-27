"""Decision package for the bank's loan origination system (E3-06).

Only a signed memo can be exported: the payload carries the CA's decision, the figures it
rests on, and the fingerprints (memo PDF SHA-256, audit-chain head, source documents)
that let the LOS side verify nothing changed after sign-off. Customer identifiers are
limited to what booking needs; no transaction-level data leaves the system.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import ConnectorError
from app.connectors.los import SCHEMA, canonical, get_los_target
from app.models import Case, CreditMemo, Document, User
from app.services import audit, consent
from app.services import memo as memo_svc


class LosError(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def build(db: Session, case_id: int) -> dict[str, Any]:
    case = db.get(Case, case_id)
    if case is None:
        raise LosError("case not found", 404)
    m = db.scalar(select(CreditMemo).where(CreditMemo.case_id == case_id))
    if m is None or m.status != "signed":
        raise LosError("sign the credit memo before sending it to the LOS")
    pkg = memo_svc.build_package(db, case_id)
    a, s_safe = pkg["analysis"], pkg["sizing_safe"]
    signer = db.get(User, m.signed_by) if m.signed_by else None
    ca_consent = consent.has(db, case_id, "credit_assessment")
    return {
        "schema": SCHEMA,
        "case": {"id": case.id, "company_name": case.company_name, "tax_id": case.tax_id, "industry": case.industry,
                 "business_age_years": case.business_age_years, "source": case.source},
        "request": {"amount": f"{case.requested_amount:.2f}", "tenor_months": case.tenor_months,
                    "sizing_tenor_months": pkg["case"]["sizing_tenor_months"],
                    "annual_rate": str(case.annual_rate), "purpose": case.purpose},
        "decision": {
            "recommendation": m.recommendation,
            "term_loan_amount": f"{m.approved_amount:.2f}" if m.approved_amount is not None else None,
            "trade_line_amount": f"{m.trade_line_amount:.2f}" if m.trade_line_amount is not None else None,
            "ca_reason": m.ca_reason, "signed_by": signer.name if signer else None,
            "signed_at": m.signed_at.isoformat() if m.signed_at else None,
        },
        "figures": {
            "period_start": a["period_start"], "period_end": a["period_end"], "months": a["months"],
            "verified_operating_revenue": a["waterfall"]["verified_operating_revenue"],
            "clean_cash_flow_monthly": a["clean_cash_flow_monthly"],
            "existing_debt_monthly": a["existing_debt_monthly"],
            "tiers": a["tiers"], "safe_limit": s_safe["safe_limit"], "policy": s_safe["policy"],
            "alt_data_haircut": (a.get("alt_data") or {}).get("haircut"),
        },
        "risk": {
            "concentration": {k: (a.get("concentration") or {}).get(k) for k in ("level", "top1_share", "hhi")},
            "anomalies": [x["kind"] for x in a.get("anomalies") or []],
            "ews": (a.get("alt_data") or {}).get("ews"),
        },
        "evidence": {
            "memo_pdf_sha256": m.pdf_sha256, "audit_head": m.audit_head, "analysis_id": m.analysis_id,
            "engine_version": a["engine_version"],
            "documents": [{"filename": d.filename, "kind": d.kind, "sha256": d.sha256}
                          for d in db.scalars(select(Document).where(Document.case_id == case_id).order_by(Document.id))],
            "consent": {"credit_assessment_version": ca_consent.version if ca_consent else None},
        },
    }


def submit(db: Session, case_id: int, user: User, ip: str | None) -> dict[str, Any]:
    payload = build(db, case_id)
    target = get_los_target()
    try:
        ref, again = target.submit(db, payload)
    except ConnectorError as e:
        raise LosError(str(e), 422) from e
    m = db.scalar(select(CreditMemo).where(CreditMemo.case_id == case_id))
    sha = hashlib.sha256(canonical(payload)).hexdigest()
    if not again or m.los_reference != ref:
        m.los_reference, m.los_submitted_at = ref, datetime.now(timezone.utc)
        audit.log(db, "los_submitted", case_id=case_id, user_id=user.id, ip=ip, target_type="memo", target_id=m.id,
                  after={"reference": ref, "payload_sha256": sha, "target": target.name, "mode": target.mode})
    db.commit()
    return {"reference": ref, "submitted_at": m.los_submitted_at.isoformat(), "payload_sha256": sha,
            "mode": target.mode, "already_submitted": again}
