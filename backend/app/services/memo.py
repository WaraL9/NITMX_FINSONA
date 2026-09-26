"""Decision package (E11-01), narrative drafting (E11-04), sign-off and PDF export (E11-03, E9-08)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import narrative
from app import storage
from app.config import settings
from app.engine import ratios
from app.memo.pdf import render_memo
from app.models import AuditEntry, Case, CreditMemo, Document, Transaction, User, WatchlistItem
from app.services import audit
from app.services.analysis import DEFAULT_POLICY, latest_analysis


class MemoError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _size(case: Case, result: dict, amount: Decimal) -> dict[str, Any]:
    haircut = Decimal(result.get("alt_data", {}).get("haircut", "0"))
    cfo = (Decimal(result["clean_cash_flow_monthly"]) * (1 - haircut)).quantize(Decimal("0.01"))
    s = ratios.size(amount, cfo, Decimal(result["existing_debt_monthly"]), case.annual_rate, case.tenor_months,
                    DEFAULT_POLICY)
    st = ratios.structure(case.requested_amount, s.safe_limit, Decimal(result.get("t1_monthly", "0")), DEFAULT_POLICY)
    return {
        "amount": f"{s.amount:.2f}", "dscr": f"{s.dscr:.4f}" if s.dscr is not None else "0",
        "new_payment": f"{s.new_payment:.2f}", "passes_min": s.passes_min, "meets_target": s.meets_target,
        "safe_limit": f"{s.safe_limit:.2f}", "max_at_min": f"{s.max_at_min:.2f}",
        "policy": {"min_dscr": str(DEFAULT_POLICY.min_dscr), "target_dscr": str(DEFAULT_POLICY.target_dscr)},
        "structure": {"needed": st.needed, "term_loan": f"{st.term_loan:.2f}", "trade_line": f"{st.trade_line:.2f}",
                      "total": f"{st.total:.2f}", "shortfall": f"{st.shortfall:.2f}",
                      "trade_line_ratio": str(DEFAULT_POLICY.trade_line_ratio)},
    }


def _facts(case: Case, a: dict, s_req: dict, s_safe: dict, n_accounts: int) -> tuple[dict[str, str], dict[str, bool]]:
    B, M = narrative.baht, narrative.millions
    w, t = a["waterfall"], a["tiers"]
    verified = Decimal(w["verified_operating_revenue"]) or Decimal(1)
    cash = a.get("cash_pattern") or {}
    alt = a.get("alt_data") or {}
    st = s_req["structure"]
    facts = {
        "company": case.company_name,
        "requested": M(case.requested_amount),
        "accounts": f"{n_accounts}",
        "gross_inflow": M(Decimal(w["gross_raw_inflow"])),
        "loops": M(Decimal(w["own_account_loops"])),
        "loop_count": f"{len(a['loops'])}",
        "owner_inflow": M(Decimal(w["owner_family_inflow"])),
        "unverified": M(Decimal(w["unverified_pending"]) + Decimal(w["unverified_excluded"])),
        "verified_revenue": M(verified),
        "t1_share": f"ร้อยละ {Decimal(t['T1_golden']) / verified * 100:.0f}",
        "cfo_monthly": B(Decimal(a["clean_cash_flow_monthly"])),
        "existing_debt": B(Decimal(a["existing_debt_monthly"])),
        "dscr_request": f"{Decimal(s_req['dscr']):.2f} เท่า",
        "min_dscr": f"{DEFAULT_POLICY.min_dscr} เท่า",
        "target_dscr": f"{DEFAULT_POLICY.target_dscr} เท่า",
        "safe_limit": M(Decimal(s_safe["amount"])),
        "trade_line": M(Decimal(st["trade_line"])),
        "structure_total": M(Decimal(st["total"])),
        "cash_count": f"{cash.get('count', 0)}",
        "cash_total": M(Decimal(cash.get("total", "0"))),
        "cash_days": "และ".join(cash.get("top_weekdays", [])),
        "haircut_pct": f"ร้อยละ {Decimal(alt.get('haircut', '0')) * 100:.0f}",
        "accepted": M(Decimal(w["accepted_by_ca"])),
    }
    flags = {
        "structure": bool(st["needed"]) and Decimal(st["trade_line"]) > 0,
        "cash_pattern": bool(cash.get("detected")),
        "liveness": bool(alt.get("liveness_confirmed")),
        "haircut": Decimal(alt.get("haircut", "0")) > 0,
        "accepted": Decimal(w["accepted_by_ca"]) > 0,
    }
    return facts, flags


def build_package(db: Session, case_id: int) -> dict[str, Any]:
    case = db.get(Case, case_id)
    if case is None:
        raise MemoError("case not found", 404)
    an = latest_analysis(db, case_id)
    if an is None:
        raise MemoError("no analysis yet — run the analysis first")
    a = {**an.result, "id": an.id, "created_at": an.created_at, "duration_ms": an.duration_ms}
    s_req = _size(case, a, case.requested_amount)
    s_safe = _size(case, a, Decimal(s_req["safe_limit"]))
    names = {u.id: u.name for u in db.scalars(select(User))}
    items = db.execute(
        select(WatchlistItem, Transaction).join(Transaction, Transaction.id == WatchlistItem.transaction_id)
        .where(WatchlistItem.case_id == case_id).order_by(WatchlistItem.suspicion_score.desc())
    ).all()
    watch = [{"id": w.id, "txn_id": t.id, "date": t.posted_at.date().isoformat(), "counterparty": t.counterparty_name,
              "amount": f"{t.credit:.2f}", "status": w.status, "reason": w.reason,
              "decided_by": names.get(w.decided_by)} for w, t in items]
    memo = ensure_draft(db, case, a, s_req, s_safe)
    return {
        "case": {"id": case.id, "company_name": case.company_name, "industry": case.industry,
                 "business_age_years": case.business_age_years, "requested_amount": f"{case.requested_amount:.2f}",
                 "purpose": case.purpose, "tenor_months": case.tenor_months, "annual_rate": str(case.annual_rate),
                 "status": case.status},
        "analysis": a,
        "sizing_request": s_req,
        "sizing_safe": s_safe,
        "watchlist": watch,
        "documents": db.query(Document).filter(Document.case_id == case_id).count(),
        "memo": _memo_out(memo, names),
    }


def _memo_out(m: CreditMemo, names: dict[int, str]) -> dict[str, Any]:
    return {
        "id": m.id, "status": m.status, "narrative": m.narrative, "narrative_source": m.narrative_source,
        "recommendation": m.recommendation,
        "approved_amount": f"{m.approved_amount:.2f}" if m.approved_amount is not None else None,
        "trade_line_amount": f"{m.trade_line_amount:.2f}" if m.trade_line_amount is not None else None,
        "ca_reason": m.ca_reason, "signed_by": names.get(m.signed_by) if m.signed_by else None,
        "signed_at": m.signed_at.isoformat() if m.signed_at else None, "analysis_id": m.analysis_id,
        "pdf_sha256": m.pdf_sha256, "audit_head": m.audit_head, "has_pdf": bool(m.pdf_path),
    }


def ensure_draft(db: Session, case: Case, a: dict, s_req: dict, s_safe: dict, regenerate: bool = False) -> CreditMemo:
    m = db.scalar(select(CreditMemo).where(CreditMemo.case_id == case.id))
    if m is None:
        # Set defaults explicitly: column defaults only apply at INSERT, and we read them below.
        m = CreditMemo(case_id=case.id, status="draft", narrative="", narrative_source="template")
        db.add(m)
    stale = m.analysis_id != a["id"] and m.narrative_source != "ca_edited"
    if m.status == "draft" and (regenerate or not m.narrative or stale):
        facts, flags = _facts(case, a, s_req, s_safe, len(case.accounts))
        n = narrative.draft(db, facts, flags, case_id=case.id)
        m.narrative, m.narrative_source, m.analysis_id = n.text, n.source, a["id"]
    db.commit()
    db.refresh(m)
    return m


def regenerate(db: Session, case_id: int) -> dict[str, Any]:
    m = db.scalar(select(CreditMemo).where(CreditMemo.case_id == case_id))
    if m and m.status == "signed":
        raise MemoError("memo already signed", 409)
    if m:
        m.narrative, m.narrative_source = "", "template"
        db.commit()
    return build_package(db, case_id)


def edit_narrative(db: Session, case_id: int, text: str, user: User, ip: str | None) -> dict[str, Any]:
    build_package(db, case_id)
    m = db.scalar(select(CreditMemo).where(CreditMemo.case_id == case_id))
    if m.status == "signed":
        raise MemoError("memo already signed", 409)
    before = m.narrative_source
    m.narrative, m.narrative_source = text.strip(), "ca_edited"
    audit.log(db, "memo_narrative_edit", case_id=case_id, user_id=user.id, ip=ip, target_type="memo",
              target_id=m.id, before={"source": before}, after={"source": "ca_edited", "chars": len(m.narrative)})
    db.commit()
    return build_package(db, case_id)


def sign(db: Session, case_id: int, user: User, ip: str | None, recommendation: str, approved_amount: Decimal | None,
         trade_line: Decimal | None, reason: str) -> dict[str, Any]:
    if user.role != "CA":
        raise MemoError("only a credit analyst can sign the memo", 403)
    pkg = build_package(db, case_id)
    case = db.get(Case, case_id)
    m = db.scalar(select(CreditMemo).where(CreditMemo.case_id == case_id))
    if m.status == "signed":
        raise MemoError("memo already signed", 409)
    if recommendation != "decline" and (approved_amount is None or approved_amount <= 0):
        raise MemoError("approved amount is required")
    if recommendation == "approve" and approved_amount != case.requested_amount:
        raise MemoError("'approve' means the requested amount; use 'approve_structured' for a different amount")
    amount = approved_amount if recommendation != "decline" else case.requested_amount
    at_approved = _size(case, pkg["analysis"], amount)
    signed_at = datetime.now(timezone.utc)

    last = db.scalar(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(1))
    head = last.hash if last else audit.GENESIS
    folder = settings.storage_dir / f"case_{case_id}"
    pdf = folder / f"credit_memo_{signed_at:%Y%m%dT%H%M%S}.pdf"
    render_memo(pkg, {
        "recommendation": recommendation,
        "approved_amount": f"{amount:.2f}",
        "trade_line_amount": f"{trade_line or 0:.2f}",
        "dscr_at_approved": f"{Decimal(at_approved['dscr']):.2f}" if recommendation != "decline" else "—",
        "narrative": m.narrative,
        "reason": reason.strip(),
        "signed_by": user.name,
        "signed_at": signed_at.replace(tzinfo=None).isoformat(timespec="seconds"),
        "audit_head": head,
    }, pdf)
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()  # of the plaintext PDF
    storage.encrypt_in_place(pdf)

    m.status, m.recommendation, m.ca_reason = "signed", recommendation, reason.strip()
    m.approved_amount = amount if recommendation != "decline" else None
    m.trade_line_amount = trade_line if recommendation != "decline" else None
    m.signed_by, m.signed_at, m.pdf_path, m.pdf_sha256, m.audit_head = user.id, signed_at, str(pdf), digest, head
    m.analysis_id = pkg["analysis"]["id"]
    case.status = "decided"
    audit.log(db, "memo_signed", case_id=case_id, user_id=user.id, ip=ip, target_type="memo", target_id=m.id,
              after={"recommendation": recommendation, "approved_amount": f"{amount:.2f}",
                     "trade_line": f"{trade_line or 0:.2f}", "dscr_at_approved": at_approved["dscr"],
                     "pdf_sha256": digest, "audit_head_in_pdf": head, "analysis_id": m.analysis_id},
              reason=reason.strip())
    db.commit()
    return build_package(db, case_id)


def reopen(db: Session, case_id: int, user: User, ip: str | None, reason: str) -> dict[str, Any]:
    """Unlock a signed memo for revision; the signed PDF and its audit record remain."""
    if user.role != "CA":
        raise MemoError("only a credit analyst can reopen the memo", 403)
    m = db.scalar(select(CreditMemo).where(CreditMemo.case_id == case_id))
    if m is None or m.status != "signed":
        raise MemoError("memo is not signed", 409)
    audit.log(db, "memo_reopened", case_id=case_id, user_id=user.id, ip=ip, target_type="memo", target_id=m.id,
              before={"status": "signed", "pdf_sha256": m.pdf_sha256}, after={"status": "draft"}, reason=reason)
    m.status = "draft"
    db.get(Case, case_id).status = "in_review"
    db.commit()
    return build_package(db, case_id)
