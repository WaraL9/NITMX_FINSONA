from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Case
from app.schemas import CaseCreate, CaseDetail, CaseSummary

router = APIRouter(prefix="/api/cases", tags=["cases"])


@router.get("", response_model=list[CaseSummary])
def list_cases(db: Session = Depends(get_db)) -> list[Case]:
    return list(db.scalars(select(Case).order_by(Case.created_at.desc())))


@router.post("", response_model=CaseDetail, status_code=201)
def create_case(body: CaseCreate, db: Session = Depends(get_db)) -> Case:
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
