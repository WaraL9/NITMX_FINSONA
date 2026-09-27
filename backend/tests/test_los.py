"""E3-06: hand-off of the signed decision to the bank's loan origination system (sandbox)."""

import re

import pytest

from tests.helpers import AUD, RM

SIGN = {"recommendation": "approve_structured", "approved_amount": "3500000", "trade_line_amount": "1000000",
        "reason": "กระแสเงินสดจริงรองรับได้ที่วงเงินปลอดภัย พร้อม Trade Line ผูก PromptBiz"}


@pytest.fixture()
def signed(client, seeded_case_id):
    client.post("/api/demo/reset")
    client.post(f"/api/cases/{seeded_case_id}/memo/regenerate")
    r = client.post(f"/api/cases/{seeded_case_id}/memo/sign", json=SIGN)
    assert r.status_code == 200, r.text
    return r.json()["memo"]


def test_export_needs_a_signed_memo(client, seeded_case_id):
    client.post("/api/demo/reset")
    r = client.get(f"/api/cases/{seeded_case_id}/los-export")
    assert r.status_code == 409
    assert client.post(f"/api/cases/{seeded_case_id}/los-export/submit").status_code == 409


def test_payload_carries_decision_figures_and_fingerprints(client, seeded_case_id, signed):
    p = client.get(f"/api/cases/{seeded_case_id}/los-export").json()
    assert p["schema"] == "finsona.los-export/v1"
    assert p["decision"]["term_loan_amount"] == "3500000.00" and p["decision"]["trade_line_amount"] == "1000000.00"
    assert p["evidence"]["memo_pdf_sha256"] == signed["pdf_sha256"] and p["evidence"]["audit_head"] == signed["audit_head"]
    docs = client.get(f"/api/cases/{seeded_case_id}/documents").json()
    assert {d["sha256"] for d in p["evidence"]["documents"]} == {d["sha256"] for d in docs}
    assert "transactions" not in str(p.keys())  # no transaction-level data leaves the system
    assert client.get(f"/api/cases/{seeded_case_id}/los-export", headers=AUD).status_code == 200
    assert client.get(f"/api/cases/{seeded_case_id}/los-export", headers=RM).status_code == 403


def test_submit_is_idempotent_audited_and_reset_by_reopen(client, seeded_case_id, signed):
    url = f"/api/cases/{seeded_case_id}/los-export/submit"
    assert client.post(url, headers=RM).status_code == 403
    first = client.post(url).json()
    assert re.fullmatch(r"LOS-\d{4}-\d{6}", first["reference"]) and first["already_submitted"] is False
    again = client.post(url).json()
    assert again["reference"] == first["reference"] and again["already_submitted"] is True
    memo = client.get(f"/api/cases/{seeded_case_id}/memo").json()["memo"]
    assert memo["los_reference"] == first["reference"]
    logged = [e for e in client.get(f"/api/cases/{seeded_case_id}/audit").json() if e["action"] == "los_submitted"]
    assert len(logged) == 1 and logged[0]["after"]["reference"] == first["reference"]

    client.post(f"/api/cases/{seeded_case_id}/memo/reopen", json={"reason": "ปรับวงเงินตามข้อมูลเพิ่มเติมจาก RM"})
    assert client.get(f"/api/cases/{seeded_case_id}/memo").json()["memo"]["los_reference"] is None
    client.post(f"/api/cases/{seeded_case_id}/memo/sign", json={**SIGN, "approved_amount": "3000000"})
    second = client.post(url).json()
    assert second["reference"] != first["reference"]


def test_sandbox_endpoint_validates(client):
    assert client.post("/sandbox/los/v1/applications", json={"schema": "x"}).status_code == 401
    r = client.post("/sandbox/los/v1/applications", json={"schema": "other/v9"}, headers={"X-Api-Key": "sandbox"})
    assert r.status_code == 422 and "missing" in r.text
