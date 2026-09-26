"""Authentication and authorisation (E14-01)."""

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.db import SessionLocal
from app.main import app
from app.models import Case, Transaction, User
from tests.helpers import AUD, CA, RM, SME, bearer


@pytest.fixture()
def anon(seeded_case_id):
    with TestClient(app) as c:
        yield c


def test_login_and_me(anon):
    r = anon.post("/api/auth/login", json={"username": "CA ", "password": "finsona-demo"})
    assert r.status_code == 200
    token = r.json()["token"]
    me = anon.get("/api/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["username"] == "ca" and me["role"] == "CA"


def test_wrong_password_same_message_and_lockout(anon):
    auth._attempts.clear()
    unknown = anon.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    wrong = anon.post("/api/auth/login", json={"username": "rm", "password": "x"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]
    for _ in range(4):
        anon.post("/api/auth/login", json={"username": "rm", "password": "x"})
    locked = anon.post("/api/auth/login", json={"username": "rm", "password": "finsona-demo"})
    assert locked.status_code == 429  # even the right password waits out the lockout
    auth._attempts.clear()


def test_no_token_or_bad_token_is_rejected(anon, seeded_case_id):
    assert anon.get(f"/api/cases/{seeded_case_id}").status_code == 401
    good = bearer(1, "CA")["Authorization"]
    tampered = good[:-3] + ("AAA" if not good.endswith("AAA") else "BBB")
    assert anon.get("/api/me", headers={"Authorization": tampered}).status_code == 401
    expired = {"Authorization": f"Bearer {auth.issue_token(1, 'CA', ttl=-1)}"}
    assert anon.get("/api/me", headers=expired).status_code == 401
    # The old demo header no longer authenticates anyone.
    assert anon.get("/api/me", headers={"X-User-Id": "1"}).status_code == 401


def test_public_endpoints(anon):
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/sme/industries").status_code == 200
    assert anon.post("/api/sme/prequal", json={"requested_amount": "1000000", "industry": "services",
                                               "monthly_revenue": "800000"}).status_code == 200


def test_disabled_user_loses_access_immediately(client):
    with SessionLocal() as db:
        db.get(User, 2).active = False
        db.commit()
    try:
        assert client.get("/api/me", headers=RM).status_code == 401
    finally:
        with SessionLocal() as db:
            db.get(User, 2).active = True
            db.commit()


@pytest.fixture()
def foreign_case(client):
    """A case the SME does not own and the RM is not assigned to."""
    r = client.post("/api/cases", json={"company_name": "อื่น ๆ", "industry": "x", "business_age_years": 1,
                                        "requested_amount": "100000", "purpose": "x", "tenor_months": 12,
                                        "annual_rate": "0.07"})
    cid = r.json()["id"]
    with SessionLocal() as db:
        db.get(Case, cid).rm_user_id = 1  # someone else
        db.commit()
    return cid


def test_case_scope_on_every_id_kind(client, seeded_case_id, foreign_case):
    # SME: own case yes, foreign case no — by case_id, document_id and txn_id alike.
    assert client.get(f"/api/cases/{seeded_case_id}", headers=SME).status_code == 200
    assert client.get(f"/api/cases/{foreign_case}", headers=SME).status_code == 404
    assert client.get(f"/api/cases/{foreign_case}", headers=RM).status_code == 404
    assert [c["id"] for c in client.get("/api/cases", headers=SME).json()] == [seeded_case_id]
    with SessionLocal() as db:
        txn = db.query(Transaction).filter(Transaction.case_id == seeded_case_id).first()
    with SessionLocal() as db:
        db.get(Case, seeded_case_id).owner_user_id = None  # temporarily not the SME's
        db.commit()
    try:
        assert client.get(f"/api/transactions/{txn.id}/lineage", headers=SME).status_code == 404
        assert client.get(f"/api/documents/{txn.document_id}/file", headers=SME).status_code == 404
    finally:
        with SessionLocal() as db:
            db.get(Case, seeded_case_id).owner_user_id = 3
            db.commit()
    assert client.get(f"/api/transactions/{txn.id}/lineage", headers=SME).status_code == 200


def test_auditor_is_read_only(client, seeded_case_id):
    assert client.get(f"/api/cases/{seeded_case_id}/analysis", headers=AUD).status_code == 200
    assert client.get("/api/audit/verify", headers=AUD).status_code == 200
    assert client.post(f"/api/cases/{seeded_case_id}/analysis", headers=AUD).status_code == 403


def test_role_restricted_actions(client, seeded_case_id):
    assert client.post(f"/api/cases/{seeded_case_id}/analysis", headers=SME).status_code == 403
    assert client.post(f"/api/cases/{seeded_case_id}/analysis", headers=RM).status_code == 403
    assert client.post("/api/cases", json={}, headers=RM).status_code in (403, 422)
    assert client.post(f"/api/cases/{seeded_case_id}/memo/regenerate", headers=RM).status_code == 403


def test_passwords_are_hashed():
    h = auth.hash_password("s3cret")
    assert "s3cret" not in h and auth.verify_password("s3cret", h) and not auth.verify_password("S3cret", h)
    assert h != auth.hash_password("s3cret")  # salted
