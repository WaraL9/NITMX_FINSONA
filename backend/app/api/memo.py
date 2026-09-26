from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import gateway
from app.api.deps import client_ip, current_user
from app.db import get_db
from app.models import CreditMemo, User
from app.schemas import LlmStatusOut, MemoPackageOut, NarrativeIn, ReasonIn, SignIn
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
def regenerate(case_id: int, db: Session = Depends(get_db)):
    return _run(svc.regenerate, db, case_id)


@router.put("/api/cases/{case_id}/memo/narrative", response_model=MemoPackageOut)
def edit_narrative(case_id: int, body: NarrativeIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
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
    return FileResponse(m.pdf_path, media_type="application/pdf", filename=Path(m.pdf_path).name,
                        content_disposition_type="inline")


@router.get("/api/llm/status", response_model=LlmStatusOut)
def llm_status():
    return gateway.status()
