"""Upload API: fingerprinting, duplicates, passwords, parsing, transactions (E2-01, E2-03)."""

import hashlib

import pytest


@pytest.fixture()
def new_case(client) -> int:
    r = client.post("/api/cases", json={"company_name": "ทดสอบอัปโหลด", "industry": "ทดสอบ",
                                        "business_age_years": 1, "requested_amount": "1000000",
                                        "purpose": "ทดสอบ", "tenor_months": 12, "annual_rate": "0.07"})
    return r.json()["id"]


def _upload(client, case_id, path, **form):
    with open(path, "rb") as f:
        return client.post(f"/api/cases/{case_id}/documents", files={"file": (path.name, f, "application/pdf")},
                           data={k: str(v) for k, v in form.items()})


def test_seeded_case_has_all_statements(client, seeded_case_id, truth):
    docs = client.get(f"/api/cases/{seeded_case_id}/documents").json()
    assert len(docs) == 4
    assert all(d["parse_report"]["continuity_ok"] for d in docs)
    assert sum(d["parse_report"]["rows"] for d in docs) == sum(len(a["rows"]) for a in truth["accounts"].values())
    assert any(d["parse_report"]["was_encrypted"] for d in docs)
    # Every statement matched a pre-registered account rather than creating a new one.
    assert not any(d["parse_report"]["account_created"] for d in docs)


def test_upload_statement(client, new_case, statement_path):
    path = statement_path("BBL_CUR")
    r = _upload(client, new_case, path)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert doc["parse_report"]["rows"] == 581
    assert doc["parse_report"]["account_created"] is True  # new case has no accounts yet
    assert doc["parse_report"]["period_start"] == "2025-12-01"

    case = client.get(f"/api/cases/{new_case}").json()
    assert case["accounts"][0]["account_no_masked"] == "xxx-x-x4521-x"

    dup = _upload(client, new_case, path)
    assert dup.status_code == 409
    assert dup.json()["code"] == "duplicate_document"
    assert dup.json()["existing_document_id"] == doc["id"]

    f = client.get(f"/api/documents/{doc['id']}/file")
    assert f.status_code == 200
    assert f.content[:5] == b"%PDF-"


def test_password_flow(client, new_case, statement_path):
    path = statement_path("KBANK_DIR")
    r = _upload(client, new_case, path)
    assert r.status_code == 422 and r.json()["code"] == "password_required"
    r = _upload(client, new_case, path, password="00000000")
    assert r.status_code == 422 and r.json()["code"] == "password_incorrect"
    r = _upload(client, new_case, path, password="15082528")
    assert r.status_code == 201, r.text
    assert r.json()["parse_report"]["was_encrypted"] is True
    # The viewer gets the decrypted copy, but the fingerprint is of the original upload.
    assert r.json()["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    f = client.get(f"/api/documents/{r.json()['id']}/file")
    assert b"/Encrypt" not in f.content


def test_rejects_non_pdf(client, new_case, tmp_path):
    p = tmp_path / "notes.pdf"
    p.write_bytes(b"hello, not a pdf")
    r = _upload(client, new_case, p)
    assert r.status_code == 422 and r.json()["code"] == "not_a_pdf"


def test_rejects_unknown_layout(client, new_case, tmp_path):
    from reportlab.pdfgen.canvas import Canvas

    p = tmp_path / "other.pdf"
    c = Canvas(str(p))
    c.drawString(72, 720, "Another bank's statement")
    c.save()
    r = _upload(client, new_case, p)
    assert r.status_code == 422 and r.json()["code"] == "unsupported_format"
    assert client.get(f"/api/cases/{new_case}/documents").json() == []  # nothing half-saved


def test_transactions_paging_and_search(client, seeded_case_id):
    page = client.get(f"/api/cases/{seeded_case_id}/transactions", params={"limit": 25}).json()
    assert page["total"] == 1205
    assert len(page["items"]) == 25
    times = [i["posted_at"] for i in page["items"]]
    assert times == sorted(times)

    hit = client.get(f"/api/cases/{seeded_case_id}/transactions", params={"q": "งานตกแต่งคลินิก"}).json()
    assert hit["total"] == 1
    row = hit["items"][0]
    assert row["credit"] == "450000.00"
    assert row["counterparty_name"] == "บจก. เอ บิลด์"
    assert row["page_no"] is not None and len(row["bbox"]) == 4
