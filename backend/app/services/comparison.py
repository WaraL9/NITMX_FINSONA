"""Scenario comparison (E8-12): the same case sized four ways, side by side.

  request         the amount asked for, on the cash flow as it stands now
  engine_only     the safe limit from evidence alone — no Watchlist decisions
  decided         the safe limit after the CA's Watchlist decisions (= the current analysis)
  all_accepted    what-if: every pending/queried Watchlist item accepted (an upper bound,
                  not a decision)

Each scenario re-runs the deterministic engine in memory with a different set of decisions
and sizes it with the same functions as the sizing endpoint; nothing is written. The
alternative-data haircut does not depend on Watchlist decisions, so all four share it.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.engine import ratios
from app.engine.types import AnalysisResult, Policy
from app.models import Case, Transaction
from app.services import policy as policy_svc
from app.services.analysis import AnalysisError, latest_analysis, load_inputs, run_engine

OPEN = ("pending", "queried")


def _2dp(v: Decimal) -> Decimal:
    """Round exactly as the stored analysis does (its figures are 2-dp strings)."""
    return Decimal(f"{v:.2f}")


def _scenario(key: str, title: str, note: str, r: AnalysisResult, decisions: dict[int, str], items: dict,
              txns: dict[int, Transaction], case: Case, haircut: Decimal, pol: Policy, evaluate: str) -> dict:
    cfo = (_2dp(r.clean_cash_flow_monthly) * (1 - haircut)).quantize(Decimal("0.01"))
    existing = r.existing_debt_monthly
    safe = ratios.size(case.requested_amount, cfo, existing, case.annual_rate, case.tenor_months, pol).safe_limit
    st = ratios.structure(case.requested_amount, safe, _2dp(r.tiers["T1_golden"] / r.months), pol)
    amount = case.requested_amount if evaluate == "request" else st.term_loan
    s = ratios.size(amount, cfo, existing, case.annual_rate, case.tenor_months, pol)

    def total(status: str) -> Decimal:
        return sum((txns[t].credit for t, d in decisions.items() if d == status and t in txns), Decimal("0"))

    counted = {t for t, d in decisions.items() if d == "accepted"}
    return {
        "key": key, "title": title, "note": note,
        "amount": s.amount, "term_loan": st.term_loan, "trade_line": st.trade_line, "total_facility": st.total,
        "cfo_monthly": cfo, "new_payment": s.new_payment, "total_debt_service": s.total_debt_service,
        "dscr": f"{s.dscr:.4f}" if s.dscr is not None else None, "dsr": f"{s.dsr:.4f}" if s.dsr is not None else None,
        "passes_min": s.passes_min, "meets_target": s.meets_target, "safe_limit": safe,
        "verified_revenue": r.waterfall["verified_operating_revenue"],
        "accepted_count": len(counted), "accepted_amount": total("accepted"),
        "open_count": sum(1 for t, w in items.items() if decisions.get(t) not in ("accepted", "excluded")),
        "accepted_ids": sorted(counted),
    }


def compare(db: Session, case: Case) -> dict:
    a = latest_analysis(db, case.id)
    if a is None:
        raise AnalysisError("no analysis yet — run POST /analysis")
    inp = load_inputs(db, case)
    pol = policy_svc.current(db)
    haircut = Decimal(a.result.get("alt_data", {}).get("haircut", "0"))
    txns = {t.id: t for t in inp.rows}
    items = inp.existing_items
    decided = dict(inp.decisions)
    engine_only: dict[int, str] = {}
    upside = {**decided, **{t: "accepted" for t, w in items.items() if w.status in OPEN}}

    runs = {"engine_only": run_engine(inp, engine_only), "decided": run_engine(inp, decided),
            "all_accepted": run_engine(inp, upside)}
    common = dict(items=items, txns=txns, case=case, haircut=haircut, pol=pol)
    scenarios = [
        _scenario("request", "ตามคำขอ", "วงเงินที่ขอ บนกระแสเงินสดปัจจุบัน (รวมการตัดสินของ CA)",
                  runs["decided"], decided, evaluate="request", **common),
        _scenario("engine_only", "วงเงินปลอดภัย (หลักฐานอย่างเดียว)", "ยังไม่นับรายการ Watchlist ใด ๆ",
                  runs["engine_only"], engine_only, evaluate="safe", **common),
        _scenario("decided", "หลังตัดสิน Watchlist", "ตามการตัดสินของ CA ที่บันทึกไว้ = ผลวิเคราะห์ปัจจุบัน",
                  runs["decided"], decided, evaluate="safe", **common),
        _scenario("all_accepted", "ถ้ารับรองรายการที่ค้างทั้งหมด", "สมมติฐานเพื่อประกอบการพิจารณา — ไม่ใช่การตัดสิน",
                  runs["all_accepted"], upside, evaluate="safe", **common),
    ]
    base = scenarios[1]["safe_limit"]
    for sc in scenarios:
        sc["safe_limit_vs_engine_only"] = sc["safe_limit"] - base
    return {"analysis_id": a.id, "haircut": haircut, "requested": case.requested_amount,
            "min_dscr": pol.min_dscr, "target_dscr": pol.target_dscr, "scenarios": scenarios}
