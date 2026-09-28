"""Utility & rent bill ingest (E2-14): PDF, phone photo (OCR + EXIF rotation), receipts;
payment matched to the statement; connector precedence; OCR gating with CA review."""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import AltDataRecord, AuditEntry, Case
from app.ocr.images import sniff_image, upright
from app.parsers.bill import parse_bill_words, text_layer_words
from app.synth.bills import SynthBill, render_bill
from tests.conftest import GENERATED
from tests.helpers import CA

BILLS = GENERATED / "bills"


@pytest.fixture(scope="module")
def samples(truth) -> dict[str, dict]:
    return {b["kind"]: b for b in truth["bills"]}


@pytest.fixture(scope="module")
def c(seeded_case_id):
    with TestClient(app, headers=CA) as client:
        yield client


# ---- parser -------------------------------------------------------------------------------

def test_pdf_bill_fields(samples):
    s = samples["electricity"]
    b = parse_bill_words(text_layer_words((BILLS / s["file"]).read_bytes()))
    assert (b.kind, b.period, b.due_date.isoformat(), f"{b.amount:.2f}") == \
        ("electricity", s["period"], s["due_date"], s["amount"])
    assert b.customer_no == s["customer_no"] and b.provider == "การไฟฟ้านครหลวง"
    assert b.paid_date is None and not b.is_receipt and b.confidence == {}
    assert set(b.bboxes) >= {"amount", "due_date"}


def test_rent_receipt_has_paid_date_and_lease_end(samples):
    s = samples["rent"]
    b = parse_bill_words(text_layer_words((BILLS / s["file"]).read_bytes()))
    assert b.is_receipt and b.kind == "rent"
    assert b.paid_date.isoformat() == s["paid_date"] and b.lease_end.isoformat() == s["lease_end"]


def test_phone_photo_is_turned_upright(samples):
    data = (BILLS / samples["water"]["file"]).read_bytes()
    assert sniff_image(data) == "image/jpeg"
    from PIL import Image
    import io
    raw = Image.open(io.BytesIO(data))
    assert raw.width > raw.height  # stored sideways, as phones do
    img = upright(data)
    assert img.height > img.width  # EXIF orientation applied


# ---- ingest + analysis --------------------------------------------------------------------

def _upload(c, case_id: int, path: Path, **form):
    mime = {".jpg": "image/jpeg", ".xml": "application/xml"}.get(path.suffix, "application/pdf")
    with open(path, "rb") as f:
        return c.post(f"/api/cases/{case_id}/documents", files={"file": (path.name, f, mime)},
                      data={k: str(v) for k, v in form.items()})


def _upload_bytes(c, case_id: int, name: str, data: bytes):
    return c.post(f"/api/cases/{case_id}/documents", files={"file": (name, data, "application/pdf")})


def _bill(c, case_id: int, doc_id: int) -> dict:
    return next(d for d in c.get(f"/api/cases/{case_id}/documents").json() if d["id"] == doc_id)["bill"]


@pytest.fixture(scope="module")
def bill_case(c, truth) -> int:
    """No utility consent (so no connector data): only uploaded bills feed the rules."""
    r = c.post("/api/cases", json={"company_name": "ทดสอบบิล", "industry": "ตกแต่งภายใน", "business_age_years": 5,
                                   "requested_amount": "1000000", "purpose": "ทดสอบ", "tenor_months": 36,
                                   "annual_rate": "0.07"})
    case_id = r.json()["id"]
    with SessionLocal() as db:
        db.get(Case, case_id).tax_id = "0105559123456"
        db.commit()
    assert _upload(c, case_id, GENERATED / truth["accounts"]["BBL_CUR"]["file"]).status_code == 201
    assert c.post(f"/api/cases/{case_id}/analysis").status_code == 200
    return case_id


def test_pdf_bill_paid_via_statement(c, bill_case, samples):
    s = samples["electricity"]
    r = _upload(c, bill_case, BILLS / s["file"])  # kind=auto
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["kind"] == "utility_bill" and doc["parse_report"]["amount"] == s["amount"]
    assert _bill(c, bill_case, doc["id"])["status"] == "pending_analysis"

    a = c.post(f"/api/cases/{bill_case}/analysis").json()
    link = _bill(c, bill_case, doc["id"])
    assert link["status"] == "used"
    assert link["paid_date"] == s["statement_payment"]["posted_at"][:10]
    txn = c.get(f"/api/cases/{bill_case}/transactions", params={"ids": str(link["transaction_id"])}).json()["items"][0]
    assert txn["debit"] == s["amount"] and s["customer_no"] in txn["description"]
    assert a["alt_data"]["uploads"]["used"] == 1 and a["alt_data"]["haircut"] == "0"


def test_photo_bill_held_until_ca_confirms(c, bill_case, samples):
    s = samples["water"]
    data = (BILLS / s["file"]).read_bytes()
    r = _upload(c, bill_case, BILLS / s["file"])
    assert r.status_code == 201, r.text
    doc = r.json()
    rep = doc["parse_report"]
    assert doc["kind"] == "utility_bill" and rep["ocr"]["provider"].startswith("sandbox")
    assert rep["low_confidence"] == ["amount"] and rep["amount"] == s["amount"]
    # The viewer gets an upright PDF; the original photo is kept byte for byte.
    view = c.get(f"/api/documents/{doc['id']}/file")
    assert view.headers["content-type"] == "application/pdf" and view.content[:5] == b"%PDF-"
    orig = c.get(f"/api/documents/{doc['id']}/file", params={"original": "true"})
    assert hashlib.sha256(orig.content).hexdigest() == hashlib.sha256(data).hexdigest() == doc["sha256"]

    a = c.post(f"/api/cases/{bill_case}/analysis").json()
    link = _bill(c, bill_case, doc["id"])
    assert link["status"] == "held_review" and link["review_status"] == "pending"
    assert a["alt_data"]["uploads"]["held_review"] == 1

    url = f"/api/cases/{bill_case}/bills/{link['record_id']}/review"
    assert c.post(url, json={"action": "confirm", "reason": "สั้น"}).status_code == 422
    assert c.post(url, json={"action": "correct", "reason": "แก้ไขโดยไม่มีค่าใหม่เลย"}).status_code == 422
    r = c.post(url, json={"action": "confirm", "reason": "ตรวจภาพถ่ายแล้ว ยอดเงินชัดเจนตรงกับที่อ่านได้"})
    assert r.status_code == 200, r.text
    assert r.json()["alt_data"]["uploads"]["held_review"] == 0
    link = _bill(c, bill_case, doc["id"])
    assert link["status"] == "used" and link["review_status"] == "confirmed"
    assert link["paid_date"] == s["statement_payment"]["posted_at"][:10]
    with SessionLocal() as db:
        e = db.query(AuditEntry).filter_by(action="bill_review", target_id=str(link["record_id"])).one()
        assert e.reason.startswith("ตรวจภาพถ่าย")
    from tests.helpers import SME
    with TestClient(app, headers=SME) as sme:  # only a CA can vouch for an OCR reading
        r = sme.post(url, json={"action": "confirm", "reason": "ผู้กู้พยายามยืนยันเอง"})
    assert r.status_code in (403, 404)


def test_rent_receipt_raises_lease_signal(c, bill_case, samples):
    s = samples["rent"]
    assert _upload(c, bill_case, BILLS / s["file"]).status_code == 201
    a = c.post(f"/api/cases/{bill_case}/analysis").json()
    assert any("สัญญาเช่า" in sig and "ก่อนสินเชื่อครบกำหนด" in sig for sig in a["alt_data"]["signals"])
    # E6-06: the loan cannot outlast the lease — 36 months requested, lease ends in 8 whole months.
    assert a["alt_data"]["lease_end"] == s["lease_end"] and a["alt_data"]["tenor_cap_months"] == 8
    capped = c.get(f"/api/cases/{bill_case}/sizing").json()
    uncapped = c.get(f"/api/cases/{bill_case}/sizing", params={"tenor_months": 36}).json()
    assert capped["tenor_months"] == 8 and uncapped["tenor_months"] == 36
    assert Decimal(capped["new_payment"]) > Decimal(uncapped["new_payment"])  # same amount, shorter term
    cmp = {x["key"]: x for x in c.get(f"/api/cases/{bill_case}/comparison").json()["scenarios"]}
    assert cmp["decided"]["safe_limit"] == capped["safe_limit"]


def test_months_between():
    from app.services.bills import months_between
    assert months_between(date(2026, 5, 31), date(2027, 2, 28)) == 8
    assert months_between(date(2026, 5, 31), date(2026, 6, 30)) == 0
    assert months_between(date(2026, 5, 1), date(2027, 5, 1)) == 12


def test_canonical_case_has_no_lease_cap(client, seeded_case_id):
    a = client.get(f"/api/cases/{seeded_case_id}/analysis").json()
    assert a["alt_data"]["tenor_cap_months"] is None
    assert client.get(f"/api/cases/{seeded_case_id}/sizing").json()["tenor_months"] == 12


def test_late_bill_triggers_haircut(c, bill_case, truth):
    """A bill due five weeks before the statement paid it -> 1 bill > 30 days late -> 5%."""
    march = next(r for r in truth["accounts"]["BBL_CUR"]["rows"]
                 if "ค่าไฟฟ้า" in r["details"] and r["at"].startswith("2026-03"))
    paid = date.fromisoformat(march["at"][:10])
    due = date.fromordinal(paid.toordinal() - 38)
    pdf = render_bill(SynthBill("electricity", "2026-02", "การไฟฟ้านครหลวง", "ทดสอบบิล", "CA-0205518", due,
                                Decimal(march["debit"])))
    r = _upload_bytes(c, bill_case, "late_electricity.pdf", pdf)
    assert r.status_code == 201, r.text
    a = c.post(f"/api/cases/{bill_case}/analysis").json()
    link = _bill(c, bill_case, r.json()["id"])
    assert link["status"] == "used" and "38 วัน" in link["note"]
    assert a["alt_data"]["late_30"] == 1 and a["alt_data"]["haircut"] == "0.05"


def test_unpaid_without_evidence_is_asked_not_punished(c, bill_case):
    pdf = render_bill(SynthBill("water", "2026-01", "การประปานครหลวง", "ทดสอบบิล", "CA-7741029",
                                date(2026, 1, 27), Decimal("9999.99")))
    r = _upload_bytes(c, bill_case, "water_jan.pdf", pdf)
    a = c.post(f"/api/cases/{bill_case}/analysis").json()
    assert _bill(c, bill_case, r.json()["id"])["status"] == "payment_not_found"
    assert a["alt_data"]["late_60_or_unpaid"] == 0 and a["alt_data"]["ews"] is False
    assert any("ควรสอบถาม" in s for s in a["alt_data"]["signals"])


def test_connector_wins_and_conflicts_are_flagged(c, bill_case, samples):
    s = samples["electricity"]
    doc_id = next(d["id"] for d in c.get(f"/api/cases/{bill_case}/documents").json()
                  if d["filename"] == s["file"])
    with SessionLocal() as db:
        db.add(AltDataRecord(case_id=bill_case, kind="electricity", period=s["period"],
                             due_date=date.fromisoformat(s["due_date"]), paid_date=date(2026, 7, 15),
                             amount=Decimal(s["amount"]), source="utility_sandbox"))
        db.commit()
    try:
        from app.services.analysis import run_analysis
        with SessionLocal() as db:
            run_analysis(db, bill_case, sync_invoices=False)
        a = c.get(f"/api/cases/{bill_case}/analysis").json()
        link = _bill(c, bill_case, doc_id)
        assert link["status"] == "conflict" and "วันชำระ" in link["note"]
        assert a["alt_data"]["uploads"]["conflict"] == 1
        # The feed's (late) record is what the rules used, and the CA sees why.
        assert a["alt_data"]["late_30"] == 2  # feed says 51 days late, plus the late February bill
        assert any("ไม่ตรงกับข้อมูลจากผู้ให้บริการ" in sig for sig in a["alt_data"]["signals"])
    finally:
        with SessionLocal() as db:
            db.query(AltDataRecord).filter_by(case_id=bill_case, source="utility_sandbox").delete()
            db.commit()


def test_images_only_for_statements_bills_and_evidence(c, bill_case):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, "PNG")
    r = c.post(f"/api/cases/{bill_case}/documents", files={"file": ("x.png", buf.getvalue(), "image/png")},
               data={"kind": "pp30"})
    assert r.status_code == 422 and r.json()["code"] == "unsupported_format"
    r = c.post(f"/api/cases/{bill_case}/documents",
               files={"file": ("y.png", b"\x89PNG\r\n\x1a\nnot really", "image/png")}, data={"kind": "auto"})
    assert r.status_code == 422 and r.json()["code"] == "not_a_pdf"


def test_rent_receipt_on_the_canonical_case_cuts_the_safe_limit(client, seeded_case_id, samples):
    """Kitti asks for 12 months; its lease ends 8 whole months after the analysis period."""
    from app.models import Document
    from app.services.analysis import run_analysis

    before = client.get(f"/api/cases/{seeded_case_id}/sizing").json()
    r = _upload(client, seeded_case_id, BILLS / samples["rent"]["file"])
    assert r.status_code == 201, r.text
    try:
        a = client.post(f"/api/cases/{seeded_case_id}/analysis").json()
        after = client.get(f"/api/cases/{seeded_case_id}/sizing").json()
        assert a["alt_data"]["tenor_cap_months"] == 8 and after["tenor_months"] == 8
        assert a["waterfall"] == client.get(f"/api/cases/{seeded_case_id}/analysis").json()["waterfall"]
        assert before["safe_limit"] == "3500000.00" and Decimal(after["safe_limit"]) < Decimal("3500000")
        memo = client.get(f"/api/cases/{seeded_case_id}/memo").json()
        assert memo["case"]["sizing_tenor_months"] == 8
    finally:
        with SessionLocal() as db:  # remove the upload (its bill record cascades) and restore the canonical state
            db.delete(db.get(Document, r.json()["id"]))
            db.commit()
            run_analysis(db, seeded_case_id, sync_invoices=False)
    assert client.get(f"/api/cases/{seeded_case_id}/sizing").json()["safe_limit"] == "3500000.00"


def test_bill_awaiting_ocr_review_blocks_signing(client, seeded_case_id, samples):
    """Like OCR'd statement rows (E2-09): nothing read uncertainly from a photo may go into a signed memo."""
    from app.models import Document
    from app.services.analysis import run_analysis

    r = _upload(client, seeded_case_id, BILLS / samples["water"]["file"])
    assert r.status_code == 201, r.text
    try:
        client.post(f"/api/cases/{seeded_case_id}/analysis")
        body = {"recommendation": "approve_structured", "approved_amount": "3500000", "trade_line_amount": "1000000",
                "reason": "กระแสเงินสดจริงรองรับได้ที่วงเงินปลอดภัย พร้อม Trade Line ผูก PromptBiz"}
        s = client.post(f"/api/cases/{seeded_case_id}/memo/sign", json=body)
        assert s.status_code == 409 and "OCR" in s.text
    finally:
        with SessionLocal() as db:
            db.delete(db.get(Document, r.json()["id"]))
            db.commit()
            run_analysis(db, seeded_case_id, sync_invoices=False)
