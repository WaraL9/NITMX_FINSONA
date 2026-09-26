from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import txn_out
from app.api.deps import client_ip, current_user
from app.db import get_db
from app.engine import ratios
from app.engine.types import Policy
from app.models import Case, Page, Transaction, User, WatchlistItem
from app.schemas import AnalysisOut, PolicyOut, SizingOut, WatchlistOut
from app.services.analysis import AnalysisError, latest_analysis, run_analysis

router = APIRouter(prefix="/api/cases/{case_id}", tags=["analysis"])

# Bank credit policy (E6-08 makes this editable per product).
DEFAULT_POLICY = Policy()


def _case(db: Session, case_id: int) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    return case


def _out(a) -> AnalysisOut:
    return AnalysisOut(**{**a.result, "id": a.id, "created_at": a.created_at, "duration_ms": a.duration_ms})


@router.post("/analysis", response_model=AnalysisOut)
def run(case_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _case(db, case_id)
    try:
        return _out(run_analysis(db, case_id, user_id=user.id, ip=client_ip(request)))
    except AnalysisError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/analysis", response_model=AnalysisOut)
def latest(case_id: int, db: Session = Depends(get_db)):
    _case(db, case_id)
    a = latest_analysis(db, case_id)
    if a is None:
        raise HTTPException(404, "no analysis yet — run POST /analysis")
    return _out(a)


@router.get("/sizing", response_model=SizingOut)
def sizing(
    case_id: int,
    amount: str | None = Query(None, description="loan amount THB; defaults to the requested amount"),
    tenor_months: int | None = Query(None, gt=0, le=360),
    annual_rate: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """DSCR/DSR for a loan size, plus the safe limit — cheap enough to call on every slider move."""
    case = _case(db, case_id)
    a = latest_analysis(db, case_id)
    if a is None:
        raise HTTPException(404, "no analysis yet — run POST /analysis")
    try:
        amt = Decimal(amount) if amount is not None else case.requested_amount
        rate = Decimal(annual_rate) if annual_rate is not None else case.annual_rate
    except InvalidOperation as e:
        raise HTTPException(422, "amount and annual_rate must be decimal numbers") from e
    if amt <= 0 or not (0 <= rate < 1):
        raise HTTPException(422, "amount must be > 0 and 0 <= annual_rate < 1")
    s = ratios.size(amt, Decimal(a.result["clean_cash_flow_monthly"]), Decimal(a.result["existing_debt_monthly"]),
                    rate, tenor_months or case.tenor_months, DEFAULT_POLICY)
    return SizingOut(
        amount=s.amount, annual_rate=s.annual_rate, tenor_months=s.tenor_months, cfo_monthly=s.cfo_monthly,
        existing_debt_monthly=s.existing_debt_monthly, new_payment=s.new_payment,
        total_debt_service=s.total_debt_service,
        dscr=f"{s.dscr:.4f}" if s.dscr is not None else None,
        dsr=f"{s.dsr:.4f}" if s.dsr is not None else None,
        passes_min=s.passes_min, meets_target=s.meets_target, safe_limit=s.safe_limit, max_at_min=s.max_at_min,
        policy=PolicyOut(min_dscr=s.policy.min_dscr, target_dscr=s.policy.target_dscr, max_dsr=s.policy.max_dsr),
    )


@router.get("/watchlist", response_model=list[WatchlistOut])
def watchlist(case_id: int, db: Session = Depends(get_db)):
    _case(db, case_id)
    rows = db.execute(
        select(WatchlistItem, Transaction, Page.page_no)
        .join(Transaction, Transaction.id == WatchlistItem.transaction_id)
        .outerjoin(Page, Page.id == Transaction.page_id)
        .where(WatchlistItem.case_id == case_id)
        .order_by(WatchlistItem.suspicion_score.desc(), Transaction.credit.desc())
    ).all()
    return [
        WatchlistOut(id=w.id, status=w.status, suspicion_score=w.suspicion_score, system_note=w.system_note,
                     reason=w.reason, transaction=txn_out(t, page_no))
        for w, t, page_no in rows
    ]
