"""RM field assistant, SME portal, pinpoint queries, evidence and consent (I5)."""

import pytest

from app.db import SessionLocal
from app.models import Query

CA, RM, SME, AUD = {"X-User-Id": "1"}, {"X-User-Id": "2"}, {"X-User-Id": "3"}, {"X-User-Id": "4"}
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 256
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture()
def query(client, seeded_case_id):
    """A fresh CA -> RM question on the 450k watchlist item; item reset afterwards."""
    items = client.get(f"/api/cases/{seeded_case_id}/watchlist").json()
    item = next(i for i in items if i["transaction"]["credit"] == "450000.00")
    r = client.post(f"/api/cases/{seeded_case_id}/watchlist/{item['id']}/decision",
                    json={"action": "query_rm", "reason": "ขอสำเนาสัญญาว่าจ้างงานตกแต่งคลินิก งวดที่ 1"}, headers=CA)
    assert r.status_code == 200
    q = client.get("/api/rm/queries", headers=RM).json()[0]
    yield q
    client.post(f"/api/cases/{seeded_case_id}/watchlist/{item['id']}/decision",
                json={"action": "reopen", "reason": "คืนสถานะหลังการทดสอบ"}, headers=CA)
    with SessionLocal() as db:
        db.query(Query).delete()
        db.commit()


def test_query_rm_creates_pinpoint_question(client, seeded_case_id, query):
    assert query["status"] == "open" and query["audience"] == "rm"
    assert query["amount"] == "450000.00" and query["txn_date"] == "2026-03-08"
    assert "สัญญาว่าจ้าง" in query["question"] and query["created_by"].startswith("คุณสมชาย")


def test_rm_answers_with_photo_and_ca_sees_it(client, seeded_case_id, query):
    r = client.post(f"/api/queries/{query['id']}/answer", data={"note": "แนบสัญญาและภาพหน้างาน"},
                    files=[("files", ("contract.jpg", JPEG, "image/jpeg")), ("files", ("site.png", PNG, "image/png"))],
                    headers=RM)
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["status"] == "answered" and [e["mime"] for e in a["evidence"]] == ["image/jpeg", "image/png"]
    assert client.post(f"/api/queries/{query['id']}/answer", data={"note": "ซ้ำ"}, headers=RM).status_code == 409
    seen = client.get(f"/api/cases/{seeded_case_id}/queries", headers=CA).json()[0]
    assert seen["evidence"][0]["sha256"] == a["evidence"][0]["sha256"]
    f = client.get(f"/api/evidence/{a['evidence'][0]['id']}/file", headers=AUD)
    assert f.status_code == 200 and f.content == JPEG
    logged = next(e for e in client.get(f"/api/cases/{seeded_case_id}/audit").json() if e["action"] == "query_answered")
    assert logged["after"]["files"][0]["sha256"] == a["evidence"][0]["sha256"]


def test_evidence_is_validated_by_content(client, query):
    fake = client.post(f"/api/queries/{query['id']}/answer", data={"note": "x"},
                       files=[("files", ("photo.jpg", b"MZ-not-an-image", "image/jpeg"))], headers=RM)
    assert fake.status_code == 422
    empty = client.post(f"/api/queries/{query['id']}/answer", data={"note": ""}, headers=RM)
    assert empty.status_code == 422


def test_sme_answers_only_after_forward(client, seeded_case_id, query):
    assert client.post(f"/api/queries/{query['id']}/answer", data={"note": "x"}, headers=SME).status_code == 403
    assert client.post(f"/api/queries/{query['id']}/forward", json={}, headers=SME).status_code == 403
    f = client.post(f"/api/queries/{query['id']}/forward", json={"note": "รบกวนถ่ายหน้าลงนาม"}, headers=RM).json()
    assert f["audience"] == "sme" and "รบกวนถ่ายหน้าลงนาม" in f["question"]
    app = client.get(f"/api/sme/applications/{seeded_case_id}", headers=SME).json()
    assert [q["id"] for q in app["questions"]] == [query["id"]]
    r = client.post(f"/api/queries/{query['id']}/answer", data={"note": "สัญญางวดที่ 1"},
                    files=[("files", ("c.jpg", JPEG, "image/jpeg"))], headers=SME)
    assert r.status_code == 200 and r.json()["answered_by"].startswith("คุณกิตติ")


def test_rm_leads_and_gaps(client, seeded_case_id):
    lead = next(l for l in client.get("/api/rm/leads", headers=RM).json() if l["case_id"] == seeded_case_id)
    assert lead["group"] == "restructure" and 0 < lead["score"] <= 100 and lead["dscr_at_request"].startswith("1.05")
    d = client.get(f"/api/rm/leads/{seeded_case_id}", headers=RM).json()
    kinds = {g["kind"] for g in d["gaps"]}
    assert {"evidence", "structure"} <= kinds
    assert client.get("/api/rm/leads", headers=SME).status_code == 403


def test_prequalification(client):
    body = {"requested_amount": "1000000", "industry": "services", "monthly_revenue": "800000"}
    assert client.post("/api/sme/prequal", json=body).json()["result"] == "high"
    r = client.post("/api/sme/prequal", json={**body, "requested_amount": "9000000"}).json()
    assert r["result"] == "mismatch" and float(r["safe_limit"]) > 0 and "ไม่ใช่การอนุมัติ" in r["disclaimer"]
    assert client.post("/api/sme/prequal", json={**body, "industry": "casino"}).status_code == 422


def test_sme_application_lifecycle_and_consent(client, statement_path):
    body = {"company_name": "ร้าน ทดสอบพอร์ทัล", "tax_id": "0105560000001", "industry": "retail",
            "business_age_years": 3, "requested_amount": "800000", "purpose": "ทุนหมุนเวียน", "tenor_months": 12,
            "mode": "fast_track", "contact_phone": "089-000-0000",
            "consents": {"credit_assessment": False, "promptbiz_data": True, "utility_data": True}}
    assert client.post("/api/sme/applications", json=body, headers=SME).status_code == 422  # consent required
    body["consents"]["credit_assessment"] = True
    body["consents"]["promptbiz_data"] = False
    app = client.post("/api/sme/applications", json=body, headers=SME).json()
    cid = app["case_id"]
    assert {c["purpose"]: c["granted"] for c in app["consents"]} == {
        "credit_assessment": True, "promptbiz_data": False, "utility_data": True}
    assert client.post(f"/api/sme/applications/{cid}/submit", headers=SME).status_code == 422  # no statement yet
    # The portal endpoints are SME-only (bank staff use the workbench APIs).
    assert client.get(f"/api/sme/applications/{cid}", headers=CA).status_code == 403
    with open(statement_path("BBL_CUR"), "rb") as f:
        up = client.post(f"/api/cases/{cid}/documents", files={"file": ("s.pdf", f, "application/pdf")}, headers=SME)
    assert up.status_code == 201
    done = client.post(f"/api/sme/applications/{cid}/submit", headers=SME).json()
    assert done["submitted_at"] and done["tracker"]["stages"][1]["status"] == "done"
    assert done["tracker"]["sla_hours_left"] > 47
    a = client.get(f"/api/cases/{cid}/analysis").json()
    assert a["connector"]["consent"] is False and a["connector"]["fetched"] == 0  # no PromptBiz consent -> no fetch
    # Documents lock after submission.
    with open(statement_path("SCB_SAV"), "rb") as f:
        late = client.post(f"/api/cases/{cid}/documents", files={"file": ("s2.pdf", f, "application/pdf")}, headers=SME)
    assert late.status_code == 409


def test_revoking_consent_removes_synced_data(client, seeded_case_id):
    url = f"/api/sme/applications/{seeded_case_id}/consents"
    try:
        client.put(url, json={"promptbiz_data": False}, headers=SME)
        a = client.post(f"/api/cases/{seeded_case_id}/analysis", headers=CA).json()
        assert a["connector"]["fetched"] == 0 and a["tiers"]["T1_golden"] == "0.00"
        log = client.get(f"/api/cases/{seeded_case_id}/audit").json()
        assert any(e["action"] == "consent_change" and e["after"]["promptbiz_data"] is False for e in log)
    finally:
        client.put(url, json={"promptbiz_data": True}, headers=SME)
        a = client.post(f"/api/cases/{seeded_case_id}/analysis", headers=CA).json()
    assert a["tiers"]["T1_golden"] == "15000000.00"


def test_sme_cannot_touch_other_cases(client, seeded_case_id, statement_path):
    r = client.post("/api/cases", json={"company_name": "อื่น", "industry": "x", "business_age_years": 1,
                                        "requested_amount": "100000", "purpose": "x", "tenor_months": 12,
                                        "annual_rate": "0.07"})
    other = r.json()["id"]
    with open(statement_path("BBL_CUR"), "rb") as f:
        up = client.post(f"/api/cases/{other}/documents", files={"file": ("s.pdf", f, "application/pdf")}, headers=SME)
    assert up.status_code == 404
    assert client.get(f"/api/sme/applications/{other}", headers=SME).status_code == 404
