"""Human-in-the-loop decisions, overrides, lineage and the audit chain (E9, E10)."""

from decimal import Decimal as D

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.models import AuditEntry

REASON = "RM แนบสัญญาว่าจ้างตกแต่งคลินิกและภาพถ่ายหน้างานแล้ว"
from tests.helpers import CA, RM


def _item(client, case_id, amount):
    return next(i for i in client.get(f"/api/cases/{case_id}/watchlist").json()
                if i["transaction"]["credit"] == amount)


@pytest.fixture()
def clean_450k(client, seeded_case_id):
    """Leave the 450k item pending after each test."""
    yield _item(client, seeded_case_id, "450000.00")
    it = _item(client, seeded_case_id, "450000.00")
    if it["status"] != "pending":
        client.post(f"/api/cases/{seeded_case_id}/watchlist/{it['id']}/decision",
                    json={"action": "reopen", "reason": "คืนสถานะหลังการทดสอบ"})


def test_every_figure_is_the_sum_of_its_rows(client, seeded_case_id):
    a = client.get(f"/api/cases/{seeded_case_id}/analysis").json()
    figures = {**a["waterfall"], **a["tiers"], **a["costs"]}
    figures.pop("own_transfers_out")
    for metric, value in figures.items():
        r = client.get(f"/api/cases/{seeded_case_id}/transactions", params={"metric": metric, "limit": 1}).json()
        got = D(r["sum_credit"]) + D(r["sum_debit"])
        assert got == D(value), metric


def test_unknown_metric(client, seeded_case_id):
    assert client.get(f"/api/cases/{seeded_case_id}/transactions", params={"metric": "nope"}).status_code == 422


def test_amount_sort(client, seeded_case_id):
    items = client.get(f"/api/cases/{seeded_case_id}/transactions",
                       params={"metric": "T1_golden", "sort": "amount_desc", "limit": 10}).json()["items"]
    amounts = [D(i["credit"]) for i in items]
    assert amounts == sorted(amounts, reverse=True)


def test_decision_requires_ca_and_reason(client, seeded_case_id, clean_450k):
    url = f"/api/cases/{seeded_case_id}/watchlist/{clean_450k['id']}/decision"
    assert client.post(url, json={"action": "accept", "reason": "สั้นไป"}, headers=CA).status_code == 422
    assert client.post(url, json={"action": "accept", "reason": REASON}, headers=RM).status_code == 403


def test_accept_recomputes_and_is_audited(client, seeded_case_id, clean_450k):
    url = f"/api/cases/{seeded_case_id}/watchlist/{clean_450k['id']}/decision"
    r = client.post(url, json={"action": "accept", "reason": REASON}, headers=CA).json()
    assert r["item"]["status"] == "accepted" and r["item"]["reason"] == REASON
    assert r["analysis"]["waterfall"]["verified_operating_revenue"] == "25450000.00"
    assert client.get(f"/api/cases/{seeded_case_id}/sizing").json()["safe_limit"] == "4140000.00"
    # State machine: can't accept twice; can reopen.
    assert client.post(url, json={"action": "accept", "reason": REASON}, headers=CA).status_code == 409
    log = client.get(f"/api/cases/{seeded_case_id}/audit").json()
    decision = next(e for e in log if e["action"] == "watchlist_decision")
    assert decision["reason"] == REASON and decision["after"]["status"] == "accepted"
    assert decision["user_name"].startswith("คุณสมชาย")


def test_query_rm_then_accept(client, seeded_case_id, clean_450k):
    url = f"/api/cases/{seeded_case_id}/watchlist/{clean_450k['id']}/decision"
    r = client.post(url, json={"action": "query_rm", "reason": "ขอสำเนาสัญญาว่าจ้างงวดที่ 1"}, headers=CA).json()
    assert r["item"]["status"] == "queried"
    assert r["analysis"]["waterfall"]["verified_operating_revenue"] == "25000000.00"  # still excluded
    r = client.post(url, json={"action": "accept", "reason": REASON}, headers=CA).json()
    assert r["item"]["status"] == "accepted"


def test_exclude_moves_money_to_excluded_bucket(client, seeded_case_id):
    it = _item(client, seeded_case_id, "700000.00")
    url = f"/api/cases/{seeded_case_id}/watchlist/{it['id']}/decision"
    try:
        a = client.post(url, json={"action": "exclude", "reason": "ฝากเงินสดก่อนยื่นกู้ ไม่มีที่มา"}, headers=CA).json()["analysis"]
        assert a["waterfall"]["unverified_excluded"] == "700000.00"
        assert a["waterfall"]["unverified_pending"] == "1300000.00"
        assert a["reconciles"] is True
    finally:
        client.post(url, json={"action": "reopen", "reason": "คืนสถานะหลังการทดสอบ"}, headers=CA)


def test_override_credit_and_debit(client, seeded_case_id):
    base = client.get(f"/api/cases/{seeded_case_id}/analysis").json()
    pp = client.get(f"/api/cases/{seeded_case_id}/transactions", params={"metric": "T3_operational", "limit": 1}).json()["items"][0]
    cost = client.get(f"/api/cases/{seeded_case_id}/transactions", params={"metric": "cost_rent", "limit": 1}).json()["items"][0]
    url = lambda t: f"/api/cases/{seeded_case_id}/transactions/{t['id']}/override"  # noqa: E731
    try:
        # A debit can't take a revenue tier.
        assert client.put(url(cost), json={"value": "T1_golden", "reason": "ทดสอบค่าที่ไม่ถูกต้อง"}, headers=CA).status_code == 422
        r = client.put(url(pp), json={"value": "non_revenue", "reason": "เป็นเงินคืนจากร้านค้า ไม่ใช่รายได้"}, headers=CA).json()
        assert r["transaction"]["tag_source"] == "ca" and r["transaction"]["tier"] is None
        a = r["analysis"]
        assert D(a["waterfall"]["verified_operating_revenue"]) == D(base["waterfall"]["verified_operating_revenue"]) - D(pp["credit"])
        assert a["waterfall"]["ca_non_revenue"] == pp["credit"] and a["reconciles"] is True
        a = client.put(url(cost), json={"value": "non_business", "reason": "ค่าเช่าบ้านเจ้าของ ไม่ใช่ของบริษัท"}, headers=CA).json()["analysis"]
        assert D(a["costs"]["business_operating"]) == D(base["costs"]["business_operating"]) - D(cost["debit"])
    finally:
        for t in (pp, cost):
            client.post(url(t) + "/revert", json={"reason": "คืนค่าหลังการทดสอบ"}, headers=CA)
    after = client.get(f"/api/cases/{seeded_case_id}/analysis").json()
    assert after["waterfall"] == base["waterfall"] and after["costs"] == base["costs"]


def test_override_rejects_watchlist_and_personal_rows(client, seeded_case_id):
    it = _item(client, seeded_case_id, "850000.00")
    r = client.put(f"/api/cases/{seeded_case_id}/transactions/{it['transaction']['id']}/override",
                   json={"value": "T3_operational", "reason": "ควรใช้ปุ่มใน Watchlist แทน"}, headers=CA)
    assert r.status_code == 422
    personal = client.get(f"/api/cases/{seeded_case_id}/transactions", params={"tag": "personal_account", "limit": 1}).json()["items"][0]
    r = client.put(f"/api/cases/{seeded_case_id}/transactions/{personal['id']}/override",
                   json={"value": "business_cost", "reason": "บัญชีส่วนตัวไม่ควร override ได้"}, headers=CA)
    assert r.status_code == 422


def test_lineage_view_is_logged_and_hash_verified(client, seeded_case_id):
    it = _item(client, seeded_case_id, "450000.00")
    lin = client.get(f"/api/transactions/{it['transaction']['id']}/lineage", headers=CA).json()
    assert lin["sha256_verified"] is True
    assert lin["transaction"]["page_no"] == it["transaction"]["page_no"]
    assert lin["page_width"] > lin["page_height"]  # landscape statement
    assert client.get(f"/api/cases/{seeded_case_id}/audit").json()[0]["action"] == "lineage_view"
    v = client.get(f"/api/documents/{lin['document']['id']}/verify").json()
    assert v["verified"] is True and v["recorded_sha256"] == v["current_sha256"]


def test_audit_chain_detects_tampering(client, seeded_case_id):
    assert client.get("/api/audit/verify").json()["ok"] is True
    with SessionLocal() as db:
        target = db.query(AuditEntry).filter(AuditEntry.action == "watchlist_decision").first() or db.query(AuditEntry).first()
        original = target.reason
        db.execute(text("UPDATE audit_log SET reason = :r WHERE id = :id"), {"r": "แก้ไขย้อนหลัง", "id": target.id})
        db.commit()
        try:
            s = client.get("/api/audit/verify").json()
            assert s["ok"] is False and s["first_bad_id"] == target.id
        finally:
            db.execute(text("UPDATE audit_log SET reason = :r WHERE id = :id"), {"r": original, "id": target.id})
            db.commit()
    assert client.get("/api/audit/verify").json()["ok"] is True
