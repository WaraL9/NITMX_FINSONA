"""The generator must reproduce the scenario totals exactly (E1-02)."""

from collections import defaultdict
from decimal import Decimal

from app.scenario import load_scenario
from app.synth import generator as g

sc = load_scenario("kitti")
gen = g.generate(sc, seed=42)
company = {k for k, a in gen.accounts.items() if a.spec.owner_type == "company"}


def _totals():
    cr, dr = defaultdict(Decimal), defaultdict(Decimal)
    for k in company:
        for t in gen.accounts[k].rows:
            cr[t.category] += t.credit
            dr[t.category] += t.debit
    return cr, dr


def test_company_credits_match_waterfall():
    cr, _ = _totals()
    assert sum(cr.values()) == sc.revenue.gross_raw_inflow
    assert cr[g.LOOP] == sc.revenue.own_account_loops
    assert cr[g.OWNER_INJECTION] == sc.revenue.owner_family_inflow
    assert cr[g.UNVERIFIED] == sc.revenue.unverified_inflow
    assert cr[g.REVENUE_T1] == sc.revenue.tiers["T1_golden"]
    assert cr[g.REVENUE_T2] == sc.revenue.tiers["T2_tax"]
    assert cr[g.REVENUE_T3] == sc.revenue.tiers["T3_operational"]


def test_company_debits_match_costs():
    _, dr = _totals()
    assert dr[g.BUSINESS_COST] == sc.costs.business_operating_6m
    assert dr[g.HOUSEHOLD] == sc.costs.household_6m
    assert dr[g.DEBT_SERVICE] == sc.existing_debt_service_monthly * sc.case.months


def test_balances_never_negative_and_chain():
    for acct in gen.accounts.values():
        bal = acct.opening_balance
        for t in acct.rows:
            bal += t.credit - t.debit
            assert t.balance == bal
            assert bal >= 0


def test_rows_inside_period():
    for acct in gen.accounts.values():
        for t in acct.rows:
            assert sc.case.period_start <= t.at.date() <= sc.case.period_end


def test_watchlist_450k_present():
    rows = [t for t in gen.accounts["BBL_CUR"].rows if t.credit == Decimal("450000.00")]
    assert len(rows) == 1
    assert rows[0].at.date().isoformat() == "2026-03-08"
    assert "งวดที่ 1 งานตกแต่งคลินิก" in rows[0].details
    assert rows[0].category == g.UNVERIFIED


def test_deterministic():
    again = g.generate(sc, seed=42)
    for k in gen.accounts:
        assert [t.truth() for t in gen.accounts[k].rows] == [t.truth() for t in again.accounts[k].rows]
