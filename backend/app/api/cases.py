from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import can_view, current_user, require_role
from app.db import get_db
from app.models import Case, User
from fastapi import Request

from app.api.deps import client_ip
from app.schemas import CaseCreate, CaseDetail, CaseSummary, ReasonIn
from app.services.retention import delete_case

router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.get("", response_model=list[CaseSummary])
def list_cases(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Case]:
    cases = db.scalars(select(Case).order_by(Case.created_at.desc()))
    return [c for c in cases if can_view(c, user)]


@router.post("", response_model=CaseDetail, status_code=201)
def create_case(body: CaseCreate, db: Session = Depends(get_db), _: User = Depends(require_role("CA"))) -> Case:
    case = Case(**body.model_dump())
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


@router.get("/{case_id}", response_model=CaseDetail)
def get_case(case_id: int, db: Session = Depends(get_db)) -> Case:
    case = db.scalar(select(Case).where(Case.id == case_id).options(selectinload(Case.accounts)))
    if case is None:
        raise HTTPException(404, "case not found")
    return case


@router.delete("/{case_id}", status_code=200)
def remove_case(case_id: int, body: ReasonIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_role("CA"))) -> dict:
    """E14-08: delete a case and all its files; the deletion itself is audit-logged."""
    try:
        summary = delete_case(db, case_id, user.id, body.reason, client_ip(request))
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    return {"deleted": case_id, "documents": len(summary["documents"]), "transactions": summary["transactions"]}
