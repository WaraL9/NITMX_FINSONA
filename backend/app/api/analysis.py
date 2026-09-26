from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import txn_out
from app.api.deps import client_ip, require_role
from app.db import get_db
from app.engine import ratios
from app.models import Case, Page, Transaction, User, WatchlistItem
from app.schemas import AltScenarioIn, AnalysisOut, PolicyOut, SizingOut, StructureOut, WatchlistOut
from app.services import policy as policy_svc
from app.services.analysis import AnalysisError, latest_analysis, run_analysis

router = APIRouter(prefix="/api/cases/{case_id}", tags=["analysis"])


def _case(db: Session, case_id: int) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    return case


def _out(a) -> AnalysisOut:
    return AnalysisOut(**{**a.result, "id": a.id, "created_at": a.created_at, "duration_ms": a.duration_ms})


@router.post("/analysis", response_model=AnalysisOut)
def run(case_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_role("CA"))):
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
    revenue_drop: str = Query("0", description="stress: 0.10 = revenue 10% lower"),
    cost_rise: str = Query("0", description="stress: 0.10 = operating costs 10% higher"),
    rate_rise_bp: int = Query(0, ge=0, le=2000, description="stress: +100 = rate one point higher"),
    db: Session = Depends(get_db),
):
    """DSCR/DSR for a loan size, the safe limit and a proposed structure — cheap enough for
    every slider move. Cash flow used is after the alternative-data haircut (E6-06);
    stress shocks (E6-05) are applied to monthly revenue and costs before the haircut."""
    case = _case(db, case_id)
    a = latest_analysis(db, case_id)
    if a is None:
        raise HTTPException(404, "no analysis yet — run POST /analysis")
    try:
        amt = Decimal(amount) if amount is not None else case.requested_amount
        rate = Decimal(annual_rate) if annual_rate is not None else case.annual_rate
        stress = ratios.Stress(Decimal(revenue_drop), Decimal(cost_rise), rate_rise_bp)
    except InvalidOperation as e:
        raise HTTPException(422, "amount, annual_rate and shocks must be decimal numbers") from e
    if amt <= 0 or not (0 <= rate < 1):
        raise HTTPException(422, "amount must be > 0 and 0 <= annual_rate < 1")
    if not (0 <= stress.revenue_drop <= 1 and 0 <= stress.cost_rise <= 1):
        raise HTTPException(422, "revenue_drop and cost_rise must be between 0 and 1")
    r = a.result
    haircut = Decimal(r.get("alt_data", {}).get("haircut", "0"))
    if stress.active and "revenue_monthly" in r:
        base_cfo = ratios.stressed_cfo(Decimal(r["revenue_monthly"]), Decimal(r["costs_monthly"]), stress)
    else:
        base_cfo = Decimal(r["clean_cash_flow_monthly"])
    cfo = (base_cfo * (1 - haircut)).quantize(Decimal("0.01"))
    rate_used = rate + Decimal(stress.rate_rise_bp) / 10000
    pol = policy_svc.current(db)
    s = ratios.size(amt, cfo, Decimal(r["existing_debt_monthly"]), rate_used, tenor_months or case.tenor_months,
                    pol)
    st = ratios.structure(case.requested_amount, s.safe_limit, Decimal(r.get("t1_monthly", "0")), pol)
    return SizingOut(
        haircut=haircut, stressed=stress.active, revenue_drop=stress.revenue_drop, cost_rise=stress.cost_rise,
        rate_rise_bp=stress.rate_rise_bp,
        structure=StructureOut(needed=st.needed, term_loan=st.term_loan, trade_line=st.trade_line, total=st.total,
                               shortfall=st.shortfall, trade_line_ratio=pol.trade_line_ratio),
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


@router.put("/sandbox/alt-scenario", response_model=AnalysisOut)
def set_alt_scenario(case_id: int, body: AltScenarioIn, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require_role("CA"))):
    """Sandbox-only what-if: switch the utility connector's scenario and re-analyse.

    Exists so the early-warning rules can be demonstrated; it never touches live data.
    """
    from app.services import audit

    case = _case(db, case_id)
    before = case.sandbox_alt_scenario
    case.sandbox_alt_scenario = body.scenario
    audit.log(db, "sandbox_scenario_change", case_id=case_id, user_id=user.id, ip=client_ip(request),
              target_type="case", target_id=case_id, before={"scenario": before}, after={"scenario": body.scenario})
    try:
        return _out(run_analysis(db, case_id, user_id=user.id, ip=client_ip(request), trigger="sandbox_scenario"))
    except AnalysisError as e:
        raise HTTPException(422, str(e)) from e
