"""E5-06 customer concentration and E4-09 anomaly flags (pure engine functions)."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from app.engine import anomalies as A
from app.engine import concentration as C

D = Decimal
T0 = datetime(2026, 1, 5, 10, 0)


def test_concentration_ranks_normalised_customers_and_flags_dominance():
    rs = [
        C.Receipt(1, T0, D("400000"), "บจก. เอบีซี"),
        C.Receipt(2, T0 + timedelta(days=31), D("200000"), "บริษัท เอบีซี จำกัด"),  # same customer
        C.Receipt(3, T0, D("300000"), "บจก. ดีอีเอฟ"),
        C.Receipt(4, T0, D("100000"), None),  # cash: unidentified
        C.Receipt(5, T0, D("50000"), "นาย ก*** ข***"),  # masked PromptPay sender
    ]
    r = C.analyze(rs, months=6)
    assert r.customers == 2 and r.identified == D("900000") and r.unidentified == D("150000")
    assert r.top[0].name == "บจก. เอบีซี" and r.top[0].amount == D("600000") and r.top[0].months_active == 2
    assert r.top1_share == D("0.6667") and r.level == "high" and r.flags
    assert r.hhi == 5556  # 66.67^2 + 33.33^2


def test_concentration_low_for_spread_customers():
    rs = [C.Receipt(i, T0, D("100000"), f"บจก. ลูกค้า {i}") for i in range(20)]
    r = C.analyze(rs, months=6)
    assert r.level == "low" and not r.flags and r.hhi == 500


def tx(i, hours, debit="0", credit="0", tag=None, tier=None, cp=None, company=True):
    return A.ATxn(i, T0 + timedelta(hours=hours), D(debit), D(credit), tag, tier, cp, company)


def test_pass_through_needs_same_or_smaller_amount_to_a_third_party():
    txns = [
        tx(1, 0, credit="500000", tag="customer_receipt", tier="T3_operational", cp="บจก. เอ"),
        tx(2, 20, debit="499000", tag="supplier_payment", cp="บจก. บี"),  # passed on less a fee -> flag
        tx(3, 0, credit="300000", tag="customer_receipt", cp="บจก. ซี"),
        tx(4, 5, debit="300500", tag="supplier_payment", cp="บจก. ดี"),  # pays out MORE -> ordinary spend
        tx(5, 0, credit="200000", tag="customer_receipt", cp="บจก. อี"),
        tx(6, 60, debit="200000", tag="supplier_payment", cp="บจก. เอฟ"),  # outside 48h
        tx(7, 0, credit="150000", tag="customer_receipt", cp="บจก. จี"),
        tx(8, 1, debit="150000", tag="own_transfer_loop", cp="บจก. จี"),  # own-account move
    ]
    found = [a for a in A.detect(txns, date(2026, 5, 31), 6) if a.kind == "pass_through"]
    assert [a.txn_ids for a in found] == [[1, 2]]


def test_period_end_owner_money_and_round_cash():
    end = date(2026, 5, 31)
    at = datetime(2026, 5, 30, 11)
    base = [A.ATxn(100 + m, datetime(2026, m, 10), D("0"), D("1000000"), "customer_receipt", "T1_golden", "x", True)
            for m in range(1, 6)]
    late = [A.ATxn(1, at, D("0"), D("300000"), "owner_injection", None, "นาย ก", True)]
    cash = [A.ATxn(10 + i, datetime(2026, 3, i + 1), D("0"), D("150000"), "cash_deposit", "T4_unverified", None, True)
            for i in range(3)]
    kinds = {a.kind: a for a in A.detect(base + late + cash, end, 5)}
    assert kinds["period_end"].txn_ids == [1]
    assert kinds["round_cash"].amount == D("450000")


def test_revenue_spike():
    txns = [A.ATxn(m, datetime(2026, m, 10), D("0"), D("1000000" if m != 4 else "2500000"), "customer_receipt",
                   "T2_tax", "x", True) for m in range(1, 7)]
    spikes = [a for a in A.detect(txns, date(2026, 6, 30), 6) if a.kind == "revenue_spike"]
    assert len(spikes) == 1 and spikes[0].txn_ids == [4]


def test_demo_cases_are_clean(client, seeded_case_id):
    a = client.get(f"/api/cases/{seeded_case_id}/analysis").json()
    assert a["anomalies"] == []
    assert a["concentration"]["level"] == "low" and a["concentration"]["customers"] >= 10
