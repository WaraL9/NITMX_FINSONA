"""E2-11: duplicate pages, overlapping statements and coverage gaps."""

import io
from datetime import date

import pytest
from pypdf import PdfReader, PdfWriter

from app.services.coverage import gaps, merge

D = date


def _pdf(path, pages: list[int]) -> bytes:
    r = PdfReader(str(path))
    w = PdfWriter()
    for i in pages:
        w.add_page(r.pages[i])
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.fixture()
def new_case(client):
    body = {"company_name": "บริษัท ทดสอบความถูกต้อง จำกัด", "industry": "ทดสอบ", "business_age_years": 3,
            "requested_amount": "1000000.00", "purpose": "ทดสอบ", "tenor_months": 12, "annual_rate": "0.07"}
    r = client.post("/api/cases", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def upload(client, case_id, data, name):
    return client.post(f"/api/cases/{case_id}/documents", files={"file": (name, data, "application/pdf")},
                       data={"kind": "statement"})


def test_duplicate_page_is_skipped(client, new_case, statement_path, truth):
    src = statement_path("SCB_SAV")
    n = len(PdfReader(str(src)).pages)
    r = upload(client, new_case, _pdf(src, [0, 1, 1, *range(2, n)]), "scb_dup_page.pdf")
    assert r.status_code == 201, r.text
    rep = r.json()["parse_report"]
    assert rep["duplicate_pages"] == [3]
    assert rep["rows"] == len(truth["accounts"]["SCB_SAV"]["rows"])
    assert rep["continuity_ok"] is True


def test_overlapping_statement_rows_are_not_counted_twice(client, new_case, statement_path, truth):
    src = statement_path("SCB_SAV")
    total = len(truth["accounts"]["SCB_SAV"]["rows"])
    first = upload(client, new_case, _pdf(src, [0, 1, 2]), "scb_part.pdf").json()["parse_report"]
    full = upload(client, new_case, src.read_bytes(), "scb_full.pdf")
    assert full.status_code == 201, full.text
    rep = full.json()["parse_report"]
    assert rep["duplicate_rows_skipped"] == first["rows"]
    rows = client.get(f"/api/cases/{new_case}/transactions", params={"limit": 1}).json()["total"]
    assert rows == total
    again = upload(client, new_case, _pdf(src, [0, 1]), "scb_again.pdf")
    assert again.status_code == 409 and again.json()["code"] == "overlapping_statement"


def test_seeded_case_coverage_is_complete(client, seeded_case_id):
    c = client.get(f"/api/cases/{seeded_case_id}/coverage").json()
    assert c["complete"] is True and len(c["accounts"]) == 4
    assert all(a["documents"] == 1 and a["missing_days"] == 0 for a in c["accounts"])


def test_gap_arithmetic():
    assert merge([(D(2026, 2, 1), D(2026, 2, 28)), (D(2026, 1, 1), D(2026, 1, 31))]) == [(D(2026, 1, 1), D(2026, 2, 28))]
    covered = [(D(2026, 1, 1), D(2026, 1, 31)), (D(2026, 3, 1), D(2026, 3, 31))]
    assert gaps(covered, D(2026, 1, 1), D(2026, 4, 30)) == [(D(2026, 2, 1), D(2026, 2, 28)), (D(2026, 4, 1), D(2026, 4, 30))]
    assert gaps([], D(2026, 1, 1), D(2026, 1, 31)) == [(D(2026, 1, 1), D(2026, 1, 31))]
