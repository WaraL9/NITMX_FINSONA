"""Unit tests for engine building blocks on small hand-made inputs."""

from datetime import date, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.engine import ratios, rules, tiers
from app.engine.transfers import detect_loops, match_own_transfers
from app.engine.types import EAccount, EFiling, EInvoice, ETxn, Policy

A = EAccount(1, "BBL", "xxx-x-x1111-x", "บจก. ทดสอบ", "company")
B = EAccount(2, "KBANK", "xxx-x-x2222-x", "บจก. ทดสอบ", "company")
C = EAccount(3, "SCB", "xxx-x-x3333-x", "บจก. ทดสอบ", "company")
DIR = EAccount(4, "KBANK", "xxx-x-x4444-x", "นายสมชาย ใจดี", "director")
ACCTS = [A, B, C, DIR]
T0 = datetime(2026, 3, 2, 9, 0)
_ids = iter(range(1, 10_000))


def out(acct, to, amount, at, code="TR-OUT"):
    return ETxn(next(_ids), acct.id, at, code, "", D(amount), D("0"), "x", to.account_no, to.bank_code)


def inn(acct, frm, amount, at):
    return ETxn(next(_ids), acct.id, at, "TR-IN", "", D("0"), D(amount), "x", frm.account_no, frm.bank_code)


# ---------- ratios ----------

def test_pmt_factor_matches_spreadsheet():
    # Excel: =PMT(7%/12, 12, -1) -> 0.086526746
    assert ratios.pmt_factor(D("0.07"), 12).quantize(D("0.000001")) == D("0.086527")
    assert ratios.pmt_factor(D("0"), 12) == D(1) / 12


def test_payment_roundtrip():
    p = ratios.payment(D("3500000"), D("0.07"), 12)
    assert p == D("302843.61")
    assert abs(ratios.principal_for_payment(p, D("0.07"), 12) - D("3500000")) < 1


def test_safe_limit_rounds_down():
    assert ratios.floor_to(D("3500000.21")) == D("3500000")
    assert ratios.floor_to(D("3499999.99")) == D("3490000")
    assert ratios.floor_to(D("-5")) == 0


def test_sizing_pass_fail_uses_unrounded():
    s = ratios.size(D("5000000"), D("613264"), D("151426"), D("0.07"), 12, Policy())
    assert not s.passes_min and s.dscr.quantize(D("0.01")) == D("1.05")
    s = ratios.size(D("3500000"), D("613264"), D("151426"), D("0.07"), 12, Policy())
    assert s.meets_target and s.safe_limit == D("3500000")


def test_negative_cash_flow_has_no_safe_limit():
    s = ratios.size(D("1000000"), D("-10000"), D("0"), D("0.07"), 12, Policy())
    assert s.safe_limit == 0 and not s.passes_min and s.dsr is None


# ---------- transfers ----------

def test_match_allows_small_fee_and_rejects_out_of_window():
    d1 = out(A, B, "100000", T0)
    c1 = inn(B, A, "99990", T0 + timedelta(minutes=3))  # 10 THB fee
    d2 = out(A, B, "50000", T0)
    c2 = inn(B, A, "50000", T0 + timedelta(hours=80))  # beyond 72h
    legs = match_own_transfers(ACCTS, [d1, c1, d2, c2])
    assert [(l.debit.id, l.credit.id) for l in legs] == [(d1.id, c1.id)]


def test_match_ignores_external_counterparties():
    ext = EAccount(9, "SCB", "xxx-x-x9999-x", "ซัพพลายเออร์", "external")
    d = ETxn(next(_ids), A.id, T0, "TR-OUT", "", D("5000"), D("0"), "ซัพพลายเออร์", ext.account_no, ext.bank_code)
    c = inn(B, A, "5000", T0)
    assert match_own_transfers(ACCTS, [d, c]) == []


def test_three_hop_loop_detected():
    txns = [
        out(A, B, "500000", T0), inn(B, A, "500000", T0 + timedelta(minutes=2)),
        out(B, DIR, "495000", T0 + timedelta(hours=5)), inn(DIR, B, "495000", T0 + timedelta(hours=5, minutes=2)),
        out(DIR, A, "490000", T0 + timedelta(hours=25)), inn(A, DIR, "490000", T0 + timedelta(hours=25, minutes=2)),
    ]
    loops = detect_loops(match_own_transfers(ACCTS, txns), {A.id, B.id, C.id})
    assert len(loops) == 1 and len(loops[0].legs) == 3
    assert loops[0].netted_amount == D("990000")  # credit legs landing in company accounts (B, A)


def test_one_way_chain_is_not_a_loop():
    txns = [out(A, B, "300000", T0), inn(B, A, "300000", T0), out(B, C, "300000", T0 + timedelta(hours=1)),
            inn(C, B, "300000", T0 + timedelta(hours=1))]
    assert detect_loops(match_own_transfers(ACCTS, txns), {1, 2, 3}) == []


@pytest.mark.parametrize("second,gap_h", [("400000", 2), ("500000", 80)])
def test_loop_needs_similar_amounts_and_short_window(second, gap_h):
    txns = [out(A, B, "500000", T0), inn(B, A, "500000", T0),
            out(B, A, second, T0 + timedelta(hours=gap_h)), inn(A, B, second, T0 + timedelta(hours=gap_h))]
    assert detect_loops(match_own_transfers(ACCTS, txns, window=timedelta(hours=100)), {1, 2}) == []


# ---------- rules ----------

def test_family_detection_by_surname():
    assert rules.surname("นายกิตติ ศรีวงศ์") == "ศรีวงศ์"
    assert rules.is_family("นางสมศรี ศรีวงศ์", {"ศรีวงศ์"})
    assert not rules.is_family("บจก. ศรีวงศ์ ก่อสร้าง", {"ศรีวงศ์"})  # a company, not a relative


@pytest.mark.parametrize("desc,code,expected", [
    ("ค่าเทอม รร.นานาชาติ บุตร", "BILL", "household"),
    ("ค่างวดรถยนต์ส่วนบุคคล สัญญา HP-1", "BILL", "household"),
    ("ชำระค่างวดสินเชื่อธุรกิจ LN-1", "LOAN", "debt_service"),
    ("PAYROLL เงินเดือนพนักงาน", "PAYROLL", "payroll"),
    ("ถอนเงินสด", "CW", "cash_withdrawal"),
    ("ค่าธรรมเนียมโอนต่างธนาคาร", "FEE", "bank_fee"),
])
def test_debit_rules(desc, code, expected):
    t = ETxn(1, 1, T0, code, desc, D("100"), D("0"))
    assert rules.tag_company_debit(t, set())[0] == expected


# ---------- tiers ----------

def test_invoice_match_with_withholding_tax():
    inv = EInvoice(1, "INV-1", date(2026, 2, 1), "บริษัท สยามคลินิก กรุ๊ป จำกัด", D("107000.00"), D("100000.00"))
    receipt = ETxn(1, 1, datetime(2026, 2, 20), "TR-IN", "", D("0"), D("104000.00"), "บจก. สยามคลินิก กรุ๊ป")
    m = tiers.match_invoices([receipt], [inv])
    assert m[1][0].id == 1 and "3%" in m[1][1]


def test_invoice_not_matched_before_issue_date():
    inv = EInvoice(1, "INV-1", date(2026, 2, 21), "บจก. เอ", D("1000.00"), D("934.58"))
    receipt = ETxn(1, 1, datetime(2026, 2, 20), "TR-IN", "", D("0"), D("1000.00"), "บจก. เอ")
    assert tiers.match_invoices([receipt], [inv]) == {}


def test_tax_capacity_never_splits_a_receipt_and_prefers_recurring():
    f = EFiling("2026-03", D("93457.94"), D("6542.06"))  # 100,000 incl. VAT
    big_one_off = ETxn(1, 1, datetime(2026, 3, 1), "TR-IN", "", D("0"), D("90000"), "นางสาวครั้งเดียว ทดสอบ")
    regular = ETxn(2, 1, datetime(2026, 3, 5), "TR-IN", "", D("0"), D("60000"), "หจก. ลูกค้าประจำ")
    got = tiers.allocate_tax_capacity([big_one_off, regular], {"2026-03": f}, {}, {rules.normalize_party("หจก. ลูกค้าประจำ")})
    assert set(got) == {2}  # 60k fits first; 90k no longer fits and is not split
