"""Alt-data rules, cash pattern, structure, stress, attribution and Thai wrapping (I4)."""

from datetime import date, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.engine import altdata, cash_pattern, ratios
from app.engine.explain import ExplainInputs, explain
from app.engine.types import ETxn, Policy
from app.memo.pdf import _COMBINING, _LEADING, wrap

AS_OF = date(2026, 5, 31)


def bills(late: dict[str, int] | None = None, unpaid: set[str] = frozenset()) -> list[altdata.EBill]:
    out = []
    for i in range(12):
        y, m = (2025, 6 + i) if i < 7 else (2026, i - 6)
        period = f"{y:04d}-{m:02d}"
        due = date(y, m, 25)
        paid = None if period in unpaid else due + timedelta(days=(late or {}).get(period, -3))
        out.append(altdata.EBill("electricity", period, due, paid, D("20000")))
    return out


@pytest.mark.parametrize("late,unpaid,haircut,ews", [
    ({}, set(), "0", False),
    ({"2026-03": 35}, set(), "0.05", False),
    ({"2026-03": 35, "2026-04": 40}, set(), "0.10", False),
    ({"2026-02": 70}, set(), "0.25", True),
    ({}, {"2026-01"}, "0.25", True),
])
def test_alt_data_rules(late, unpaid, haircut, ews):
    r = altdata.evaluate(bills(late, unpaid), AS_OF)
    assert r.haircut == D(haircut) and r.ews is ews
    assert r.liveness_confirmed is (not late and not unpaid)


def test_old_lateness_outside_six_months_is_ignored():
    assert altdata.evaluate(bills({"2025-07": 40}), AS_OF).haircut == 0


def _cw(day: date, hour=8):
    return ETxn(day.toordinal(), 1, datetime.combine(day, datetime.min.time()).replace(hour=hour), "CW",
                "ถอนเงินสด", D("50000"), D("0"))


def test_cash_pattern_detects_weekday_rhythm():
    mondays = [date(2026, 1, 5) + timedelta(weeks=i) for i in range(14)]
    assert cash_pattern.detect([_cw(d) for d in mondays]).detected
    scattered = [date(2026, 1, 5) + timedelta(days=i * 3) for i in range(14)]
    assert not cash_pattern.detect([_cw(d) for d in scattered]).detected
    assert not cash_pattern.detect([_cw(d) for d in mondays[:5]]).detected  # too few


def test_structure_matches_demo_case():
    st = ratios.structure(D("5000000"), D("3500000"), D("2500000"), Policy())
    assert st.needed and st.term_loan == D("3500000") and st.trade_line == D("1000000") and st.total == D("4500000")
    # Trade line is capped by the shortfall and rounded down to 100k.
    st = ratios.structure(D("5000000"), D("4140000"), D("2500000"), Policy())
    assert st.trade_line == D("800000")
    assert not ratios.structure(D("3000000"), D("3500000"), D("2500000"), Policy()).needed


def test_stress_lowers_cash_flow():
    base = ratios.stressed_cfo(D("4166666.67"), D("3553402.67"), ratios.Stress())
    assert base == D("613264.00")
    hit = ratios.stressed_cfo(D("4166666.67"), D("3553402.67"), ratios.Stress(D("0.05"), D("0.05"), 0))
    assert hit < base


def test_attribution_by_ablation():
    x = ExplainInputs(months=6, cfo_monthly=D("613264"), cfo_monthly_before_haircut=D("613264"),
                      existing_debt_monthly=D("151426"), annual_rate=D("0.07"), tenor_months=12,
                      requested=D("5000000"),
                      tiers={"T1_golden": D("15000000"), "T2_tax": D("8000000"), "T3_operational": D("2000000")},
                      household=D("900000"), pending_unverified=D("2000000"), loops=D("3800000"),
                      owner_inflow=D("1200000"), haircut=D("0"), cash_pattern_detected=True,
                      cash_total=D("3062000"), policy=Policy())
    base, drivers = explain(x)
    by = {d.key: d for d in drivers}
    assert base == D("3500000")
    assert by["T1_golden"].impact == D("3500000")  # without Golden revenue nothing is lendable
    assert by["existing_debt"].impact == D("-1750000")
    assert by["household"].impact > 0 and by["unverified"].impact > 0
    assert [d.kind for d in drivers] == sorted([d.kind for d in drivers], key=["positive", "risk", "info"].index)


def test_thai_wrap_keeps_marks_attached():
    text = ("บริษัทมีกระแสเงินสดสุทธิเฉลี่ยต่อเดือนเพียงพอต่อการผ่อนชำระหนี้เดิมและหนี้ใหม่ภายใต้เงื่อนไขที่กำหนด"
            "ซึ่งสอดคล้องกับหลักการให้สินเชื่ออย่างรับผิดชอบของธนาคารแห่งประเทศไทย")
    from app.synth.statement_pdf import _ensure_fonts
    from reportlab.pdfbase import pdfmetrics

    _ensure_fonts()
    lines = wrap(text, "Sarabun", 8.5, 180)
    assert len(lines) > 2 and "".join(lines) == text
    for ln in lines:
        assert ln and ln[0] not in _COMBINING and ln[-1] not in _LEADING
        assert pdfmetrics.stringWidth(ln, "Sarabun", 8.5) <= 180 + 12  # a trailing mark may overhang slightly
