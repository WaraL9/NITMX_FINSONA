"""E1-06 — the engine, fed by the real ingest pipeline, reproduces the demo case exactly.

PDF statements + ภ.พ.30 PDFs -> parsers -> PromptBiz sandbox connector -> engine -> API.
Numbers come from data/scenario_kitti.yaml `expected`; per-row tiers and loops are
checked against the generator's ground truth.
"""

from decimal import Decimal as D

from app.db import SessionLocal
from app.models import Account, Transaction, WatchlistItem
from app.scenario import load_scenario
from app.services.analysis import run_analysis

sc = load_scenario("kitti")
EXP = sc.expected
TIER_OF = {"revenue_t1_golden": "T1_golden", "revenue_t2_tax": "T2_tax",
           "revenue_t3_operational": "T3_operational", "unverified": "T4_unverified"}


def _money(s: str) -> D:
    return D(s)


def test_waterfall_and_cash_flow(client, seeded_case_id):
    a = client.get(f"/api/cases/{seeded_case_id}/analysis").json()
    w, t = a["waterfall"], a["tiers"]
    assert a["reconciles"] is True
    assert _money(w["gross_raw_inflow"]) == sc.revenue.gross_raw_inflow
    assert _money(w["own_account_loops"]) == sc.revenue.own_account_loops
    assert _money(w["owner_family_inflow"]) == sc.revenue.owner_family_inflow
    assert _money(w["unverified_pending"]) == sc.revenue.unverified_inflow
    assert _money(w["verified_operating_revenue"]) == EXP["verified_operating_revenue"]
    for k in ("T1_golden", "T2_tax", "T3_operational"):
        assert _money(t[k]) == sc.revenue.tiers[k]
    assert _money(a["costs"]["business_operating"]) == sc.costs.business_operating_6m
    assert _money(a["costs"]["household"]) == sc.costs.household_6m
    assert _money(a["clean_cash_flow_period"]) == EXP["clean_operating_cash_flow_6m"]
    assert _money(a["clean_cash_flow_monthly"]) == EXP["clean_operating_cash_flow_monthly"]
    assert _money(a["existing_debt_monthly"]) == sc.existing_debt_service_monthly
    assert a["connector"]["mode"] == "sandbox" and a["connector"]["fetched"] > 0


def test_sizing_story(client, seeded_case_id):
    s = client.get(f"/api/cases/{seeded_case_id}/sizing").json()
    assert D(s["dscr"]).quantize(D("0.01")) == EXP["dscr_at_request"]
    assert s["passes_min"] is False
    assert _money(s["safe_limit"]) == EXP["safe_limit_at_target"]
    assert _money(s["max_at_min"]) == EXP["max_at_min_dscr_approx"]
    s = client.get(f"/api/cases/{seeded_case_id}/sizing", params={"amount": "3500000"}).json()
    assert D(s["dscr"]).quantize(D("0.01")) == EXP["dscr_at_safe_limit"]
    assert s["meets_target"] is True


def test_every_row_gets_the_true_tier_and_loop(seeded_case_id, truth):
    with SessionLocal() as db:
        accounts = {a.account_no_masked: a.id for a in db.query(Account).filter(Account.case_id == seeded_case_id)}
        rows = {(t.account_id, t.row_index): t for t in db.query(Transaction).filter(Transaction.case_id == seeded_case_id)}
    wrong_tier, loop_groups = [], {}
    for acct in truth["accounts"].values():
        aid = accounts[acct["account_no_masked"]]
        for i, e in enumerate(acct["rows"]):
            got = rows[(aid, i)]
            if e["category"] in TIER_OF and got.tier != TIER_OF[e["category"]]:
                wrong_tier.append((acct["file"], i, e["category"], got.tier))
            if e["loop_id"]:
                loop_groups.setdefault(e["loop_id"], set()).add(got.loop_id)
            else:
                assert got.loop_id is None, (acct["file"], i)
    assert wrong_tier == []
    # Each true loop maps to exactly one detected loop, and they are all distinct.
    assert all(len(v) == 1 and None not in v for v in loop_groups.values())
    assert len({next(iter(v)) for v in loop_groups.values()}) == len(sc.loops)


def test_watchlist(client, seeded_case_id):
    items = client.get(f"/api/cases/{seeded_case_id}/watchlist").json()
    got = {(i["transaction"]["posted_at"][:10], i["transaction"]["credit"]) for i in items}
    assert got == {(str(w.date), f"{w.amount:.2f}") for w in sc.watchlist}
    clinic = next(i for i in items if i["transaction"]["credit"] == "450000.00")
    assert "งวดที่ 1 งานตกแต่งคลินิก" in clinic["system_note"]
    assert clinic["transaction"]["page_no"] and clinic["transaction"]["bbox"]
    assert items[0]["transaction"]["code"] == "CD"  # the pre-application cash deposit ranks most suspicious


def test_accepting_450k_moves_the_safe_limit(client, seeded_case_id):
    with SessionLocal() as db:
        item = next(w for w in db.query(WatchlistItem).filter(WatchlistItem.case_id == seeded_case_id)
                    if db.get(Transaction, w.transaction_id).credit == D("450000.00"))
        item.status = "accepted"
        db.commit()
        try:
            run_analysis(db, seeded_case_id)
            a = client.get(f"/api/cases/{seeded_case_id}/analysis").json()
            assert _money(a["waterfall"]["accepted_by_ca"]) == D("450000.00")
            assert _money(a["waterfall"]["verified_operating_revenue"]) == D("25450000.00")
            assert a["reconciles"] is True
            s = client.get(f"/api/cases/{seeded_case_id}/sizing").json()
            assert _money(s["safe_limit"]) == EXP["safe_limit_after_accepting_450k_approx"]
            # The decision survives re-analysis.
            db.refresh(item)
            assert item.status == "accepted"
        finally:
            item.status = "pending"
            db.commit()
            run_analysis(db, seeded_case_id)


def test_pp30_documents(client, seeded_case_id, truth):
    docs = [d for d in client.get(f"/api/cases/{seeded_case_id}/documents").json() if d["kind"] == "pp30"]
    assert len(docs) == len(truth["pp30"])
    for d in docs:
        r = d["parse_report"]
        e = truth["pp30"][r["period"]]
        for k in ("sales", "output_vat", "purchases", "input_vat", "vat_payable"):
            assert r["amounts"][k] == e[k]
            top, bottom = e["bands"][k]
            mid = (r["bboxes"][k][1] + r["bboxes"][k][3]) / 2
            assert top <= mid <= bottom
        assert r["warnings"] == []


def test_sandbox_requires_consent(client):
    assert client.get(f"/sandbox/promptbiz/v1/sellers/{sc.case.tax_id}/invoices").status_code == 401
    r = client.get(f"/sandbox/promptbiz/v1/sellers/{sc.case.tax_id}/invoices", headers={"X-Consent-Token": "t"})
    assert r.status_code == 200 and r.json()["mode"] == "sandbox" and r.json()["count"] > 0
