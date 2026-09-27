from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.ai import gateway
from app.api.deps import client_ip, current_user, require_role
from app.db import get_db
from app.models import CreditMemo, LlmCall, User
from app.schemas import LlmCallOut, LlmStatusOut, LosSubmitOut, MemoPackageOut, NarrativeIn, ReasonIn, SignIn
from app.services import los_export
from app.services import memo as svc

router = APIRouter(tags=["memo"])


def _run(fn, *args):
    try:
        return fn(*args)
    except svc.MemoError as e:
        raise HTTPException(e.status, str(e)) from e


@router.get("/api/cases/{case_id}/memo", response_model=MemoPackageOut)
def get_memo(case_id: int, db: Session = Depends(get_db)):
    """Decision package (E11-01): everything the 1-page memo shows, plus the draft state."""
    return _run(svc.build_package, db, case_id)


@router.post("/api/cases/{case_id}/memo/regenerate", response_model=MemoPackageOut)
def regenerate(case_id: int, db: Session = Depends(get_db), _: User = Depends(require_role("CA"))):
    return _run(svc.regenerate, db, case_id)


@router.put("/api/cases/{case_id}/memo/narrative", response_model=MemoPackageOut)
def edit_narrative(case_id: int, body: NarrativeIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_role("CA"))):
    return _run(svc.edit_narrative, db, case_id, body.narrative, user, client_ip(request))


@router.post("/api/cases/{case_id}/memo/sign", response_model=MemoPackageOut)
def sign(case_id: int, body: SignIn, request: Request, db: Session = Depends(get_db),
         user: User = Depends(current_user)):
    return _run(svc.sign, db, case_id, user, client_ip(request), body.recommendation, body.approved_amount,
                body.trade_line_amount, body.reason)


@router.post("/api/cases/{case_id}/memo/reopen", response_model=MemoPackageOut)
def reopen(case_id: int, body: ReasonIn, request: Request, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    return _run(svc.reopen, db, case_id, user, client_ip(request), body.reason)


@router.get("/api/cases/{case_id}/memo/pdf", response_class=FileResponse)
def memo_pdf(case_id: int, db: Session = Depends(get_db)):
    m = db.scalar(select(CreditMemo).where(CreditMemo.case_id == case_id))
    if m is None or not m.pdf_path or not Path(m.pdf_path).exists():
        raise HTTPException(404, "no signed memo PDF yet")
    return storage.response(Path(m.pdf_path), "application/pdf", Path(m.pdf_path).name)


@router.get("/api/cases/{case_id}/llm-calls", response_model=list[LlmCallOut])
def llm_calls(case_id: int, db: Session = Depends(get_db)):
    """E14-04: the exact masked text each AI call carried for this case."""
    return list(db.scalars(select(LlmCall).where(LlmCall.case_id == case_id).order_by(LlmCall.id.desc()).limit(20)))


@router.get("/api/llm/status", response_model=LlmStatusOut)
def llm_status():
    return gateway.status()


def _los(fn, *args):
    try:
        return fn(*args)
    except los_export.LosError as e:
        raise HTTPException(e.status, str(e)) from e


@router.get("/api/cases/{case_id}/los-export")
def los_payload(case_id: int, db: Session = Depends(get_db), _: User = Depends(require_role("CA", "AUDITOR"))) -> dict:
    """E3-06: the versioned decision package exactly as it is sent to the LOS."""
    return _los(los_export.build, db, case_id)


@router.post("/api/cases/{case_id}/los-export/submit", response_model=LosSubmitOut)
def los_submit(case_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("CA"))):
    """E3-06: hand the signed decision to the loan origination system (idempotent)."""
    return _los(los_export.submit, db, case_id, user, client_ip(request))
