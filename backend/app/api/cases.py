from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import can_view, current_user, require_role
from app.db import get_db
from app.models import Case, User
from app.schemas import CaseCreate, CaseDetail, CaseSummary

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
