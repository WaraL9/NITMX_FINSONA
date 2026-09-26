"""The scenario file must be internally consistent before any engine is built on it.

These are arithmetic checks on the SPEC. E1-06 later checks the ENGINE against it.
"""

from decimal import ROUND_HALF_UP, Decimal

from app.scenario import load_scenario

sc = load_scenario("kitti")
company_keys = {a.key for a in sc.accounts if a.owner_type == "company"}


def pmt_factor(annual_rate: Decimal, months: int) -> Decimal:
    r = annual_rate / 12
    return r / (1 - (1 + r) ** -months)


def test_waterfall_adds_up():
    rev = sc.revenue
    verified = rev.gross_raw_inflow - rev.own_account_loops - rev.owner_family_inflow - rev.unverified_inflow
    assert verified == sc.expected["verified_operating_revenue"]
    assert sum(rev.tiers.values()) == verified


def test_loop_credit_legs_into_company_accounts_equal_netted_total():
    total = sum(leg.amount for loop in sc.loops for leg in loop.legs if leg.to in company_keys)
    assert total == sc.revenue.own_account_loops


def test_loops_return_to_origin():
    for loop in sc.loops:
        assert loop.legs[0].from_ == loop.legs[-1].to, loop.id
        for a, b in zip(loop.legs, loop.legs[1:]):
            assert a.to == b.from_, loop.id
            assert a.at < b.at, loop.id


def test_watchlist_sums_to_unverified():
    assert sum(w.amount for w in sc.watchlist) == sc.revenue.unverified_inflow
    assert any(w.amount == Decimal("450000.00") and str(w.date) == "2026-03-08" for w in sc.watchlist)


def test_cash_flow():
    cfo = sc.expected["verified_operating_revenue"] - sc.costs.business_operating_6m
    assert cfo == sc.expected["clean_operating_cash_flow_6m"]
    assert cfo / sc.case.months == sc.expected["clean_operating_cash_flow_monthly"]


def test_dscr_story():
    f = pmt_factor(sc.loan_request.annual_rate, sc.loan_request.tenor_months)
    assert f.quantize(Decimal("0.000001")) == sc.expected["pmt_factor_12m_7pct"]
    cfo_m = sc.expected["clean_operating_cash_flow_monthly"]
    debt = sc.existing_debt_service_monthly

    def dscr(principal: Decimal) -> Decimal:
        return (cfo_m / (debt + principal * f)).quantize(Decimal("0.01"), ROUND_HALF_UP)

    assert dscr(sc.loan_request.amount) == sc.expected["dscr_at_request"]
    assert dscr(sc.expected["safe_limit_at_target"]) == sc.expected["dscr_at_safe_limit"]

    safe = (cfo_m / sc.policy.target_dscr - debt) / f
    assert abs(safe - sc.expected["safe_limit_at_target"]) < 1000  # within 1,000 THB of the round figure
