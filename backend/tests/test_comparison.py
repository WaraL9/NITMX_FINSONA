"""Scenario comparison (E8-12) on the canonical Kitti case (docs/BACKLOG.md §3):
request 5.0M -> DSCR 1.05; safe limit 3.5M; accept the 450k -> 4.14M."""

from decimal import Decimal as D

import pytest


def _by_key(c) -> dict:
    return {s["key"]: s for s in c["scenarios"]}


@pytest.fixture()
def item_450k(client, seeded_case_id):
    items = client.get(f"/api/cases/{seeded_case_id}/watchlist").json()
    item = next(i for i in items if i["transaction"]["credit"] == "450000.00")
    assert item["status"] == "pending"
    yield item
    client.post(f"/api/cases/{seeded_case_id}/watchlist/{item['id']}/decision",
                json={"action": "reopen", "reason": "คืนสถานะหลังการทดสอบ"})


def test_comparison_before_any_decision(client, seeded_case_id):
    c = client.get(f"/api/cases/{seeded_case_id}/comparison").json()
    s = _by_key(c)
    assert [x["key"] for x in c["scenarios"]] == ["request", "engine_only", "decided", "all_accepted"]
    req = s["request"]
    assert req["amount"] == "5000000.00" and req["dscr"].startswith("1.05") and not req["passes_min"]
    assert s["engine_only"]["safe_limit"] == s["decided"]["safe_limit"] == "3500000.00"
    assert s["decided"]["term_loan"] == "3500000.00" and s["decided"]["trade_line"] == "1000000.00"
    assert s["decided"]["dscr"].startswith("1.35") and s["decided"]["meets_target"]
    assert s["decided"]["safe_limit_vs_engine_only"] == "0.00" and s["decided"]["accepted_count"] == 0
    # The upper bound counts every open Watchlist item.
    up = s["all_accepted"]
    assert up["accepted_count"] == s["decided"]["open_count"] > 0
    assert D(up["safe_limit"]) > D("4140000") and D(up["safe_limit_vs_engine_only"]) > 0


def test_decided_column_is_the_current_analysis(client, seeded_case_id):
    """The comparison re-runs the engine; with the stored decisions it must equal the stored figures."""
    s = _by_key(client.get(f"/api/cases/{seeded_case_id}/comparison").json())["decided"]
    a = client.get(f"/api/cases/{seeded_case_id}/analysis").json()
    sizing = client.get(f"/api/cases/{seeded_case_id}/sizing").json()
    assert s["verified_revenue"] == a["waterfall"]["verified_operating_revenue"]
    assert s["cfo_monthly"] == sizing["cfo_monthly"] and s["safe_limit"] == sizing["safe_limit"]
    assert s["trade_line"] == sizing["structure"]["trade_line"]


def test_comparison_after_accepting_450k(client, seeded_case_id, item_450k):
    r = client.post(f"/api/cases/{seeded_case_id}/watchlist/{item_450k['id']}/decision",
                    json={"action": "accept", "reason": "ลูกค้ายืนยันสัญญางานคลินิก งวดที่ 1 พร้อมใบเสนอราคา"})
    assert r.status_code == 200, r.text
    s = _by_key(client.get(f"/api/cases/{seeded_case_id}/comparison").json())
    assert s["engine_only"]["safe_limit"] == "3500000.00"  # evidence alone is unchanged
    assert s["decided"]["safe_limit"] == "4140000.00"
    assert s["decided"]["safe_limit_vs_engine_only"] == "640000.00"
    assert s["decided"]["accepted_count"] == 1 and s["decided"]["accepted_amount"] == "450000.00"
    assert s["decided"]["accepted_ids"] == [item_450k["transaction"]["id"]]
    assert s["decided"]["open_count"] == s["all_accepted"]["accepted_count"] - 1


def test_comparison_is_read_only(client, seeded_case_id):
    before = client.get(f"/api/cases/{seeded_case_id}/analysis").json()["id"]
    client.get(f"/api/cases/{seeded_case_id}/comparison")
    assert client.get(f"/api/cases/{seeded_case_id}/analysis").json()["id"] == before
