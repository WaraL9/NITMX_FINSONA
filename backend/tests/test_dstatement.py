"""dStatement connector (E3-04): signed bank statements pulled with consent; imported where
nothing covers the dates, verified against uploaded statements where something does."""

import hashlib
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.connectors.dstatement import get_statement_source, verify
from app.db import SessionLocal
from app.main import app
from app.models import Case, Transaction
from app.services import consent
from tests.conftest import GENERATED
from tests.helpers import CA

KITTI_TAX = "0105559123456"
SOMJAI = settings.data_dir / "generated" / "somjai"


@pytest.fixture(scope="module")
def c(seeded_case_id):
    with TestClient(app, headers=CA) as client:
        yield client


def _case(c, tax_id: str, dstatement_consent: bool = True) -> int:
    r = c.post("/api/cases", json={"company_name": "ทดสอบ dStatement", "industry": "ตกแต่งภายใน",
                                   "business_age_years": 5, "requested_amount": "1000000", "purpose": "ทดสอบ",
                                   "tenor_months": 12, "annual_rate": "0.07"})
    case_id = r.json()["id"]
    with SessionLocal() as db:
        db.get(Case, case_id).tax_id = tax_id
        consent.record(db, case_id, {"credit_assessment": True, "dstatement_data": dstatement_consent}, None)
        db.commit()
    return case_id


def _pull(c, case_id: int, bank: str, account: str, **extra):
    return c.post(f"/api/cases/{case_id}/dstatement", json={"bank_code": bank, "account_no": account, **extra})


def _upload(c, case_id: int, path, password: str | None = None):
    with open(path, "rb") as f:
        return c.post(f"/api/cases/{case_id}/documents", files={"file": (path.name, f, "application/pdf")},
                      data={"kind": "auto", **({"password": password} if password else {})})


def _rows(case_id: int) -> list[tuple]:
    with SessionLocal() as db:
        return [(t.posted_at, t.code, t.channel, t.description, t.debit, t.credit, t.balance, t.counterparty_name,
                 t.counterparty_bank, t.counterparty_account)
                for t in db.query(Transaction).filter_by(case_id=case_id).order_by(Transaction.posted_at,
                                                                                    Transaction.row_index)]


def test_signature_and_consent():
    src = get_statement_source()
    s = src.fetch_statement(KITTI_TAX, "BBL", "4521", None, None, consent_token="t")
    assert verify(s) and len(s.statement["transactions"]) == 581
    s.statement["transactions"][0]["credit"] = "999999.00"  # edited in transit
    assert not verify(s)
    with pytest.raises(Exception):
        src.fetch_statement(KITTI_TAX, "BBL", "4521", None, None, consent_token="")


def test_sandbox_http_api(c):
    body = {"tax_id": KITTI_TAX, "bank_code": "KBANK", "account_no": "xxx-x-x7788-x", "from": "2026-01-01",
            "to": "2026-01-31"}
    assert c.post("/sandbox/dstatement/v1/statements", json=body).status_code == 401
    r = c.post("/sandbox/dstatement/v1/statements", json=body, headers={"X-Consent-Token": "t"})
    assert r.status_code == 200
    st = r.json()["statement"]
    assert all(t["posted_at"].startswith("2026-01") for t in st["transactions"])
    # The opening balance is the balance before the first returned row.
    first = st["transactions"][0]
    assert Decimal(st["opening_balance"]) - Decimal(first["debit"]) + Decimal(first["credit"]) == Decimal(first["balance"])
    assert c.post("/sandbox/dstatement/v1/statements", json={**body, "account_no": "0000"},
                  headers={"X-Consent-Token": "t"}).status_code == 404


def test_pull_imports_the_same_rows_a_pdf_gives(c, truth):
    pulled, uploaded = _case(c, KITTI_TAX), _case(c, KITTI_TAX)
    r = _pull(c, pulled, "BBL", "xxx-x-x4521-x")
    assert r.status_code == 201, r.text
    doc = r.json()
    rep = doc["parse_report"]
    assert doc["kind"] == "statement" and doc["page_count"] == 0 and rep["rows"] == 581
    assert rep["continuity_ok"], rep["continuity_breaks"]
    assert rep["account_created"] and rep["verification"] is None, (rep["account_created"], rep["verification"])
    assert rep["source"]["signature_verified"] and rep["source"]["imported"] == 581
    assert _upload(c, uploaded, GENERATED / truth["accounts"]["BBL_CUR"]["file"]).status_code == 201
    assert _rows(pulled) == _rows(uploaded)  # same schema, same values, same counterparties
    # Stored as delivered: the fingerprint is of the signed bank document.
    f = c.get(f"/api/documents/{doc['id']}/file")
    assert hashlib.sha256(f.content).hexdigest() == doc["sha256"]
    assert json.loads(f.content)["key_id"] == rep["source"]["key_id"]
    # Rows have no page to point at; lineage still resolves to the bank document.
    t = c.get(f"/api/cases/{pulled}/transactions", params={"limit": 1}).json()["items"][0]
    assert t["page_no"] is None and t["bbox"] is None and t["extractor_version"] == "dstatement-v1"
    lin = c.get(f"/api/transactions/{t['id']}/lineage").json()
    assert lin["document"]["id"] == doc["id"] and lin["sha256_verified"] is True
    # Pulling the identical statement again is a duplicate.
    assert _pull(c, pulled, "BBL", "4521").json()["code"] == "duplicate_document"
    assert c.post(f"/api/cases/{pulled}/analysis").status_code == 200


def test_pull_verifies_an_untouched_pdf(c, truth):
    case_id = _case(c, KITTI_TAX)
    assert _upload(c, case_id, GENERATED / truth["accounts"]["KBANK_SAV"]["file"]).status_code == 201
    before = len(_rows(case_id))
    rep = _pull(c, case_id, "KBANK", "7788").json()["parse_report"]
    assert rep["source"]["imported"] == 0 and len(_rows(case_id)) == before
    v = rep["verification"]
    assert v["compared"] == v["matched"] == 245
    assert v["differs_count"] == v["case_only_count"] == v["bank_only_count"] == 0
    a = c.post(f"/api/cases/{case_id}/analysis").json()
    assert not any(x["kind"] == "bank_record_mismatch" for x in a["anomalies"])


def test_pull_catches_an_edited_pdf(c, truth):
    """Simulate a doctored statement: one receipt inflated, one withdrawal removed."""
    case_id = _case(c, KITTI_TAX)
    assert _upload(c, case_id, GENERATED / truth["accounts"]["KBANK_SAV"]["file"]).status_code == 201
    with SessionLocal() as db:
        rows = db.query(Transaction).filter_by(case_id=case_id).order_by(Transaction.posted_at).all()
        inflated = next(t for t in rows if t.credit > 0)
        inflated.credit += Decimal("100000.00")
        hidden = next(t for t in rows[10:] if t.debit > 0)
        hidden_at = hidden.posted_at
        db.delete(hidden)
        inflated_id = inflated.id
        db.commit()
    v = _pull(c, case_id, "KBANK", "7788").json()["parse_report"]["verification"]
    assert v["matched"] == 243 and v["differs_count"] == 1 and v["bank_only_count"] == 1
    assert v["differs"][0]["transaction_id"] == inflated_id and "credit" in v["differs"][0]["fields"]
    assert v["bank_only"][0]["posted_at"] == hidden_at.isoformat()
    a = c.post(f"/api/cases/{case_id}/analysis").json()
    flag = next(x for x in a["anomalies"] if x["kind"] == "bank_record_mismatch")
    assert flag["severity"] == "high" and inflated_id in flag["txn_ids"]


def test_pull_fills_dates_no_statement_covers(c, truth):
    case_id = _case(c, KITTI_TAX)
    assert _upload(c, case_id, GENERATED / truth["accounts"]["KBANK_DIR"]["file"], password="15082528").status_code == 201
    with SessionLocal() as db:  # keep only December, as if the PDF covered one month
        for t in db.query(Transaction).filter_by(case_id=case_id).all():
            if t.posted_at.month != 12:
                db.delete(t)
        db.commit()
        kept = db.query(Transaction).filter_by(case_id=case_id).count()
    rep = _pull(c, case_id, "KBANK", "9021").json()["parse_report"]
    assert rep["verification"]["matched"] == kept and rep["source"]["imported"] == 32 - kept
    assert len(_rows(case_id)) == 32


def test_pull_shows_what_ocr_misread(c):
    """A scanned statement vs the bank: the OCR misreads show up as amount differences."""
    truth = json.loads((SOMJAI / "truth.json").read_text(encoding="utf-8"))
    scan = SOMJAI / truth["accounts"]["SCB_SAV"]["file"]
    rec = json.loads((settings.data_dir / "generated" / "ocr_recorded" /
                      f"{hashlib.sha256(scan.read_bytes()).hexdigest()}.json").read_text(encoding="utf-8"))
    case_id = _case(c, "0105561123458")
    assert _upload(c, case_id, scan).status_code == 201
    v = _pull(c, case_id, "SCB", truth["accounts"]["SCB_SAV"]["account_no_masked"]).json()["parse_report"]["verification"]
    assert v["differs_count"] == len(rec["truth"]) > 0
    assert v["case_only_count"] == v["bank_only_count"] == 0
    bank_values = {vals[1] for d in v["differs"] for vals in d["fields"].values()}
    assert {m["actual"].replace(",", "") for m in rec["truth"]} <= bank_values


def test_pull_needs_consent_and_a_known_account(c):
    no_consent = _case(c, KITTI_TAX, dstatement_consent=False)
    r = _pull(c, no_consent, "BBL", "4521")
    assert r.status_code == 403 and r.json()["code"] == "consent_required"
    other = _case(c, KITTI_TAX)
    r = _pull(c, other, "KTB", "1234")
    assert r.status_code == 404 and r.json()["code"] == "account_not_found"
