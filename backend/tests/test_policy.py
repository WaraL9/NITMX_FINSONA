"""Editable, versioned credit policy (E6-08)."""

from decimal import Decimal as D

from tests.helpers import RM


def test_policy_change_moves_the_numbers_and_is_audited(client, seeded_case_id):
    base = client.get(f"/api/cases/{seeded_case_id}/sizing").json()
    assert client.get("/api/policy").json()["current"]["target_dscr"] == "1.35"
    try:
        r = client.put("/api/policy", json={"target_dscr": "1.30", "reason": "ทดลองผ่อนเกณฑ์สำหรับกลุ่มรับเหมา"})
        assert r.status_code == 200 and r.json()["current"]["target_dscr"] == "1.30"
        s = client.get(f"/api/cases/{seeded_case_id}/sizing").json()
        assert D(s["safe_limit"]) > D(base["safe_limit"]) and s["policy"]["target_dscr"] == "1.30"
        a = client.get(f"/api/cases/{seeded_case_id}/analysis").json()
        assert any(d["key"] == "T1_golden" for d in a["drivers"])  # analysis re-ran under the new policy
        log = next(e for e in client.get("/api/audit").json() if e["action"] == "policy_change")
        assert log["before"]["target_dscr"] == "1.35" and log["after"]["target_dscr"] == "1.30"
    finally:
        client.put("/api/policy", json={"target_dscr": "1.35", "reason": "คืนค่านโยบายหลังการทดสอบ"})
    assert client.get(f"/api/cases/{seeded_case_id}/sizing").json()["safe_limit"] == base["safe_limit"]
    assert len(client.get("/api/policy").json()["history"]) >= 2


def test_policy_validation_and_permissions(client):
    bad = client.put("/api/policy", json={"min_dscr": "1.40", "target_dscr": "1.30", "reason": "เป้าหมายต่ำกว่าขั้นต่ำ"})
    assert bad.status_code == 422
    assert client.put("/api/policy", json={"max_dsr": "5", "reason": "ค่านอกกรอบที่อนุญาต"}).status_code == 422
    assert client.put("/api/policy", json={"target_dscr": "1.30", "reason": "RM ไม่มีสิทธิ์"}, headers=RM).status_code == 403


def test_global_audit_filter_and_csv(client):
    from tests.helpers import AUD, SME

    rows = client.get("/api/audit", params={"action": "login"}, headers=AUD)
    assert rows.status_code == 200 and all(e["action"] == "login" for e in rows.json())
    csv = client.get("/api/audit.csv", headers=AUD)
    assert csv.status_code == 200 and csv.text.startswith("\ufeffid,ts_utc")
    assert client.get("/api/audit", headers=SME).status_code == 403
