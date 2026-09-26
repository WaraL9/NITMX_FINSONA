"""RM field assistant, SME portal, pinpoint queries and evidence (E12, E13, E10-05, E14-02)."""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.api.deps import can_view, client_ip, current_user, require_role
from app.db import get_db
from app.models import Case, Document, Evidence, Query, User
from app.schemas import (
    ApplicationIn,
    ApplicationOut,
    ConsentState,
    ForwardIn,
    GapOut,
    IndustryOut,
    LeadDetailOut,
    LeadOut,
    PrequalIn,
    PrequalOut,
    QueryOut,
)
from app.services import audit, consent, field
from app.services import queries as qsvc
from app.services.analysis import AnalysisError, run_analysis

router = APIRouter(tags=["field"])
public = APIRouter(tags=["sme-public"])  # pre-qualification works before login


def _err(e: qsvc.QueryError):
    return HTTPException(e.status, str(e))


def _case_for(db: Session, case_id: int, user: User) -> Case:
    case = db.get(Case, case_id)
    if case is None or not can_view(case, user):
        raise HTTPException(404, "case not found")
    return case


def _lead_out(lead: field.Lead) -> dict:
    c = lead.case
    return {"case_id": c.id, "company_name": c.company_name, "industry": c.industry,
            "requested_amount": c.requested_amount, "status": c.status, "submission_mode": c.submission_mode,
            "contact_phone": c.contact_phone, "score": lead.score, "group": lead.group, "reasons": lead.reasons,
            "dscr_at_request": lead.dscr_at_request, "safe_limit": lead.safe_limit, "open_queries": lead.open_queries}


# ---------------- queries & evidence ----------------

@router.get("/api/cases/{case_id}/queries", response_model=list[QueryOut])
def case_queries(case_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _case_for(db, case_id, user)
    rows = db.scalars(select(Query).where(Query.case_id == case_id).order_by(Query.id.desc()))
    if user.role == "SME":
        rows = [q for q in rows if q.audience == "sme"]
    return [qsvc.serialize(db, q) for q in rows]


@router.post("/api/queries/{query_id}/forward", response_model=QueryOut)
def forward(query_id: int, body: ForwardIn, request: Request, db: Session = Depends(get_db),
            user: User = Depends(current_user)):
    q = db.get(Query, query_id)
    if q is None:
        raise HTTPException(404, "question not found")
    try:
        return qsvc.serialize(db, qsvc.forward_to_sme(db, q, user, body.note, client_ip(request)))
    except qsvc.QueryError as e:
        raise _err(e) from e


@router.post("/api/queries/{query_id}/answer", response_model=QueryOut)
async def answer(query_id: int, request: Request, note: str = Form(""), files: list[UploadFile] = File(default=[]),
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.get(Query, query_id)
    if q is None:
        raise HTTPException(404, "question not found")
    uploads = [qsvc.Upload(f.filename or "evidence", await f.read()) for f in files]
    try:
        return qsvc.serialize(db, qsvc.answer(db, q, user, note, uploads, client_ip(request)))
    except qsvc.QueryError as e:
        db.rollback()
        raise _err(e) from e


@router.get("/api/evidence/{evidence_id}/file", response_class=FileResponse)
def evidence_file(evidence_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ev = db.get(Evidence, evidence_id)
    if ev is None:
        raise HTTPException(404, "evidence not found")
    _case_for(db, ev.case_id, user)
    if not Path(ev.storage_path).exists():
        raise HTTPException(410, "file missing from storage")
    return storage.response(Path(ev.storage_path), ev.mime, ev.filename)


# ---------------- RM field assistant ----------------

@router.get("/api/rm/leads", response_model=list[LeadOut])
def leads(db: Session = Depends(get_db), user: User = Depends(require_role("RM", "CA"))):
    cases = db.scalars(select(Case).order_by(Case.created_at.desc())).all()
    mine = [c for c in cases if user.role == "CA" or c.rm_user_id in (None, user.id)]
    order = {"ready": 0, "restructure": 1, "needs_data": 2}
    scored = sorted((field.score_case(db, c) for c in mine), key=lambda l: (order[l.group], -l.score))
    return [_lead_out(l) for l in scored]


@router.get("/api/rm/leads/{case_id}", response_model=LeadDetailOut)
def lead_detail(case_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("RM", "CA"))):
    case = _case_for(db, case_id, user)
    lead = field.score_case(db, case)
    qs = db.scalars(select(Query).where(Query.case_id == case_id).order_by(Query.id.desc()))
    return {**_lead_out(lead), "gaps": [GapOut(**g.__dict__) for g in field.gaps(db, case)],
            "queries": [qsvc.serialize(db, q) for q in qs]}


@router.get("/api/rm/queries", response_model=list[QueryOut])
def rm_inbox(db: Session = Depends(get_db), user: User = Depends(require_role("RM"))):
    rows = db.execute(select(Query, Case).join(Case, Case.id == Query.case_id).order_by(Query.id.desc())).all()
    return [qsvc.serialize(db, q) for q, c in rows if c.rm_user_id in (None, user.id)]


# ---------------- SME portal ----------------

DISCLAIMER = ("ผลประเมินเบื้องต้นจากข้อมูลที่ท่านกรอก ไม่ใช่การอนุมัติสินเชื่อ "
              "ผลจริงขึ้นกับการตรวจสอบกระแสเงินสดจากเอกสารและดุลยพินิจของเจ้าหน้าที่")


@public.get("/api/sme/industries", response_model=list[IndustryOut])
def industries():
    return [{"key": k, "label": v[0]} for k, v in field.INDUSTRY_MARGINS.items()]


@public.post("/api/sme/prequal", response_model=PrequalOut)
def prequal(body: PrequalIn):
    if body.industry not in field.INDUSTRY_MARGINS:
        raise HTTPException(422, "unknown industry")
    p = field.prequalify(body.requested_amount, body.industry, body.monthly_revenue, body.existing_debt_monthly,
                         body.annual_rate, body.tenor_months)
    return PrequalOut(result=p.result, indicative_cfo=p.indicative_cfo,
                      dscr=f"{p.dscr:.4f}" if p.dscr is not None else None, safe_limit=p.safe_limit,
                      reasons=p.reasons, unlocks=p.unlocks, disclaimer=DISCLAIMER)


def _application(db: Session, case: Case) -> dict:
    grants = consent.current(db, case.id)
    qs = db.scalars(select(Query).where(Query.case_id == case.id, Query.audience == "sme").order_by(Query.id.desc()))
    return {
        "case_id": case.id, "company_name": case.company_name, "industry": case.industry,
        "requested_amount": case.requested_amount, "purpose": case.purpose, "tenor_months": case.tenor_months,
        "status": case.status, "submission_mode": case.submission_mode, "submitted_at": case.submitted_at,
        "documents": db.query(Document).filter(Document.case_id == case.id).count(),
        "tracker": field.tracker(db, case),
        "consents": [ConsentState(purpose=p, label=label, granted=bool(grants[p] and grants[p].granted),
                                  recorded_at=grants[p].recorded_at if grants[p] else None)
                     for p, label in consent.PURPOSES.items()],
        "questions": [qsvc.serialize(db, q) for q in qs],
    }


def _own_case(db: Session, case_id: int, user: User) -> Case:
    case = db.get(Case, case_id)
    if case is None or case.owner_user_id != user.id:
        raise HTTPException(404, "application not found")
    return case


@router.get("/api/sme/applications", response_model=list[ApplicationOut])
def my_applications(db: Session = Depends(get_db), user: User = Depends(require_role("SME"))):
    cases = db.scalars(select(Case).where(Case.owner_user_id == user.id).order_by(Case.created_at.desc()))
    return [_application(db, c) for c in cases]


@router.get("/api/sme/applications/{case_id}", response_model=ApplicationOut)
def my_application(case_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("SME"))):
    return _application(db, _own_case(db, case_id, user))


@router.post("/api/sme/applications", response_model=ApplicationOut, status_code=201)
def create_application(body: ApplicationIn, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(require_role("SME"))):
    if body.industry not in field.INDUSTRY_MARGINS:
        raise HTTPException(422, "unknown industry")
    if not body.consents.get("credit_assessment"):
        raise HTTPException(422, "consent to use data for credit assessment is required to apply")
    rm = db.scalar(select(User).where(User.role == "RM").order_by(User.id).limit(1))
    case = Case(company_name=body.company_name, tax_id=body.tax_id, industry=field.INDUSTRY_MARGINS[body.industry][0],
                business_age_years=body.business_age_years, requested_amount=body.requested_amount,
                purpose=body.purpose, tenor_months=body.tenor_months, annual_rate=Decimal("0.07"), status="draft",
                source="sme_portal", owner_user_id=user.id, rm_user_id=rm.id if rm else None,
                submission_mode=body.mode, contact_phone=body.contact_phone)
    db.add(case)
    db.flush()
    try:
        consent.record(db, case.id, body.consents, user.id, client_ip(request))
    except ValueError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    audit.log(db, "application_created", case_id=case.id, user_id=user.id, ip=client_ip(request),
              target_type="case", target_id=case.id,
              after={"mode": body.mode, "requested_amount": f"{body.requested_amount:.2f}"})
    db.commit()
    return _application(db, case)


@router.put("/api/sme/applications/{case_id}/consents", response_model=ApplicationOut)
def update_consents(case_id: int, body: dict[str, bool], request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_role("SME"))):
    case = _own_case(db, case_id, user)
    try:
        consent.record(db, case.id, body, user.id, client_ip(request))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    db.commit()
    return _application(db, case)


@router.post("/api/sme/applications/{case_id}/submit", response_model=ApplicationOut)
def submit(case_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("SME"))):
    case = _own_case(db, case_id, user)
    if not consent.has(db, case.id, "credit_assessment"):
        raise HTTPException(422, "consent for credit assessment is required")
    if db.query(Document).filter(Document.case_id == case.id, Document.kind == "statement").count() == 0:
        raise HTTPException(422, "upload at least one bank statement first")
    case.submitted_at = case.submitted_at or datetime.now(timezone.utc)
    audit.log(db, "application_submitted", case_id=case.id, user_id=user.id, ip=client_ip(request),
              target_type="case", target_id=case.id)
    try:
        run_analysis(db, case.id, user_id=user.id, ip=client_ip(request), trigger="sme_submit")
    except AnalysisError as e:
        raise HTTPException(422, str(e)) from e
    db.refresh(case)
    return _application(db, case)
