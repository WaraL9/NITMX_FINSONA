"""e-Tax invoice ingest (E2-13): ETDA XML, PDF with embedded XML, PDF text fallback, and the
receipts the uploaded invoices verify as Tier 1."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.db import SessionLocal
from app.models import Case, Invoice
from app.parsers.base import ParseError, UnsupportedFormat
from app.parsers.etax import parse_etax_pdf, parse_etax_xml
from tests.conftest import GENERATED

ETAX = GENERATED / "etax"
KITTI_TAX_ID = "0105559123456"


@pytest.fixture(scope="module")
def samples(truth) -> list[dict]:
    assert len(truth["etax"]) == 3
    return truth["etax"]


def _xml(sample: dict) -> bytes:
    return (ETAX / sample["xml"]).read_bytes()


# ---- parser -------------------------------------------------------------------------------

def test_xml_fields(samples):
    s = samples[0]
    inv = parse_etax_xml(_xml(s))
    assert (inv.source, inv.invoice_no, inv.type_code, inv.issue_date.isoformat()) == \
        ("xml", s["invoice_no"], "388", s["issue_date"])
    assert inv.seller_tax_id == KITTI_TAX_ID  # 18-digit TXID (tax ID + branch) -> 13-digit tax ID
    assert inv.buyer_name == s["buyer_name"]
    assert (inv.subtotal, inv.vat, inv.total) == (Decimal(s["subtotal"]), Decimal(s["vat"]), Decimal(s["total"]))
    assert inv.signature == "absent"
    assert any("ลายมือชื่อดิจิทัล" in w for w in inv.warnings)


def test_xml_signature_detected(samples):
    signature = (b'<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#"><ds:SignedInfo/>'
                 b'<ds:SignatureValue>AA==</ds:SignatureValue></ds:Signature>')
    xml = _xml(samples[0]).replace(b"</rsm:TaxInvoice_CrossIndustryInvoice>",
                                   signature + b"</rsm:TaxInvoice_CrossIndustryInvoice>")
    inv = parse_etax_xml(xml)
    assert inv.signature == "present_unverified"
    assert not any("ลายมือชื่อดิจิทัล" in w for w in inv.warnings)


def test_xml_rejects_dtd_and_non_sales(samples):
    with pytest.raises(ParseError, match="DTD"):
        parse_etax_xml(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>')
    credit_note = _xml(samples[0]).replace(b"<ram:TypeCode>388</ram:TypeCode>", b"<ram:TypeCode>81</ram:TypeCode>")
    with pytest.raises(UnsupportedFormat, match="ใบลดหนี้"):
        parse_etax_xml(credit_note)
    with pytest.raises(UnsupportedFormat):
        parse_etax_xml(b"<Invoice><ID>1</ID></Invoice>")


def test_xml_total_mismatch_is_a_warning(samples):
    s = samples[0]
    xml = _xml(s).replace(f"<ram:GrandTotalAmount>{s['total']}".encode(), b"<ram:GrandTotalAmount>999999.00")
    inv = parse_etax_xml(xml)
    assert inv.total == Decimal("999999.00")
    assert any("ยอดรวมทั้งสิ้นไม่เท่ากับ" in w for w in inv.warnings)


@pytest.mark.parametrize("key,source", [("pdf", "pdf_embedded_xml"), ("print_pdf", "pdf_text")])
def test_pdf_paths_agree_with_xml(samples, key, source):
    s = samples[1]
    inv = parse_etax_pdf((ETAX / s[key]).read_bytes())
    ref = parse_etax_xml(_xml(s))
    assert inv.source == source
    for f in ("invoice_no", "issue_date", "seller_tax_id", "buyer_name", "buyer_tax_id", "subtotal", "vat", "total"):
        assert getattr(inv, f) == getattr(ref, f), f
    # Amounts carry their place on the page for the lineage viewer.
    assert set(inv.bboxes) == {"subtotal", "vat", "total"}
    assert all(b.x1 > b.x0 and b.bottom > b.top for b in inv.bboxes.values())


# ---- ingest + engine ----------------------------------------------------------------------

def _new_case(client, tax_id: str | None) -> int:
    r = client.post("/api/cases", json={"company_name": "ทดสอบ e-Tax", "industry": "ตกแต่งภายใน",
                                        "business_age_years": 5, "requested_amount": "1000000",
                                        "purpose": "ทดสอบ", "tenor_months": 36, "annual_rate": "0.07"})
    case_id = r.json()["id"]
    with SessionLocal() as db:
        db.get(Case, case_id).tax_id = tax_id
        db.commit()
    return case_id


def _upload(client, case_id: int, path, **form):
    mime = "application/xml" if path.suffix == ".xml" else "application/pdf"
    with open(path, "rb") as f:
        return client.post(f"/api/cases/{case_id}/documents", files={"file": (path.name, f, mime)},
                           data={k: str(v) for k, v in form.items()})


def _receipt(client, case_id: int, sample: dict) -> dict:
    items = client.get(f"/api/cases/{case_id}/transactions", params={"limit": 500}).json()["items"]
    paid_at = datetime.fromisoformat(sample["paid_at"])
    return next(t for t in items if datetime.fromisoformat(t["posted_at"]).replace(tzinfo=None) == paid_at
                and t["credit"] == sample["paid_amount"])


@pytest.fixture(scope="module")
def etax_case(client_module, truth, samples) -> int:
    """A case with only the account that received the sampled receipts."""
    c = client_module
    case_id = _new_case(c, KITTI_TAX_ID)
    r = _upload(c, case_id, GENERATED / truth["accounts"][samples[0]["account"]]["file"])
    assert r.status_code == 201, r.text
    assert c.post(f"/api/cases/{case_id}/analysis").status_code == 200
    return case_id


@pytest.fixture(scope="module")
def client_module(seeded_case_id):
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.helpers import CA

    with TestClient(app, headers=CA) as c:
        yield c


def test_uploaded_etax_invoice_verifies_receipt_as_tier1(client_module, etax_case, samples):
    c, s = client_module, samples[0]
    before = _receipt(c, etax_case, s)
    assert before["tier"] != "T1_golden"

    r = _upload(c, etax_case, ETAX / s["xml"])  # kind=auto: XML is recognised as an e-Tax invoice
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["kind"] == "etax_invoice" and doc["page_count"] == 0
    rep = doc["parse_report"]
    assert (rep["invoice_no"], rep["source"], rep["amounts"]["total"]) == (s["invoice_no"], "xml", s["total"])
    listed = next(d for d in c.get(f"/api/cases/{etax_case}/documents").json() if d["id"] == doc["id"])
    assert listed["invoice"]["status"] == "pending_analysis"  # uploaded after the last analysis

    a = c.post(f"/api/cases/{etax_case}/analysis").json()
    after = _receipt(c, etax_case, s)
    assert after["tier"] == "T1_golden"
    assert "e-Tax" in after["tag_reason"] and s["invoice_no"] in after["tag_reason"]
    assert a["etax"] == {"uploaded": 1, "matched": 1, "duplicates_of_promptbiz": []}

    # Lineage invariant: the T1 figure is exactly the rows its filter returns.
    rows = c.get(f"/api/cases/{etax_case}/transactions", params={"metric": "T1_golden", "limit": 500}).json()
    assert rows["sum_credit"] == a["tiers"]["T1_golden"]
    assert after["id"] in {t["id"] for t in rows["items"]}

    link = next(d for d in c.get(f"/api/cases/{etax_case}/documents").json() if d["id"] == doc["id"])["invoice"]
    assert link["status"] == "matched" and link["transaction_id"] == after["id"]
    assert link["paid_amount"] == s["paid_amount"]

    # The stored original is the XML exactly as uploaded.
    f = c.get(f"/api/documents/{doc['id']}/file")
    assert f.status_code == 200 and f.content == _xml(s)


def test_same_invoice_twice_is_rejected(client_module, etax_case, samples):
    s = samples[0]
    first = next(d for d in client_module.get(f"/api/cases/{etax_case}/documents").json()
                 if d["kind"] == "etax_invoice" and d["parse_report"]["invoice_no"] == s["invoice_no"])
    r = _upload(client_module, etax_case, ETAX / s["pdf"])  # different file, same invoice
    assert r.status_code == 409 and r.json()["code"] == "duplicate_invoice"
    assert r.json()["existing_document_id"] == first["id"]


def test_pdf_uploads_auto_detected(client_module, etax_case, samples):
    c = client_module
    embedded = _upload(c, etax_case, ETAX / samples[1]["pdf"])
    printed = _upload(c, etax_case, ETAX / samples[2]["print_pdf"])
    assert embedded.status_code == 201 and printed.status_code == 201, (embedded.text, printed.text)
    assert embedded.json()["kind"] == printed.json()["kind"] == "etax_invoice"
    assert embedded.json()["parse_report"]["source"] == "pdf_embedded_xml"
    assert printed.json()["parse_report"]["source"] == "pdf_text"
    assert printed.json()["page_count"] == 1
    a = c.post(f"/api/cases/{etax_case}/analysis").json()
    assert a["etax"]["matched"] == 3
    for s in samples:
        assert _receipt(c, etax_case, s)["tier"] == "T1_golden"

    # The memo appendix lists the uploaded invoices apart from the PromptBiz feed.
    from app.services import appendix
    with SessionLocal() as db:
        ap = appendix.build(db, db.get(Case, etax_case), a)
    assert ap["external"]["etax_invoices"] == 3 and ap["external"]["invoices"] == 0
    assert ap["external"]["etax_total"] == f"{sum(Decimal(s['total']) for s in samples):.2f}"


def test_promptbiz_copy_wins_over_uploaded_duplicate(client_module, etax_case, samples):
    """The same invoice from the network and from an upload must verify at most one receipt."""
    c, s = client_module, samples[0]
    with SessionLocal() as db:
        up = db.query(Invoice).filter_by(case_id=etax_case, invoice_no=s["invoice_no"]).one()
        db.add(Invoice(case_id=etax_case, source="promptbiz_sandbox", invoice_no=up.invoice_no,
                       issue_date=up.issue_date, buyer_name=up.buyer_name, seller_tax_id=up.seller_tax_id,
                       subtotal=up.subtotal, vat=up.vat, amount=up.amount))
        db.commit()
    try:
        # Re-run without a PromptBiz sync (the case has no consent, so a sync would drop the copy).
        from app.services.analysis import run_analysis
        with SessionLocal() as db:
            run_analysis(db, etax_case, sync_invoices=False)
        a = c.get(f"/api/cases/{etax_case}/analysis").json()
        assert a["etax"]["duplicates_of_promptbiz"] == [s["invoice_no"]]
        receipt = _receipt(c, etax_case, s)
        assert receipt["tier"] == "T1_golden" and "PromptBiz" in receipt["tag_reason"]
        link = next(d for d in c.get(f"/api/cases/{etax_case}/documents").json()
                    if d["invoice"] and d["invoice"]["invoice_no"] == s["invoice_no"])["invoice"]
        assert link["status"] == "duplicate_of_promptbiz"
    finally:
        with SessionLocal() as db:
            db.query(Invoice).filter_by(case_id=etax_case, source="promptbiz_sandbox").delete()
            db.commit()


def test_invoice_from_another_seller_is_rejected(client, samples):
    case_id = _new_case(client, "0105999999999")
    r = _upload(client, case_id, ETAX / samples[0]["xml"])
    assert r.status_code == 422 and r.json()["code"] == "seller_mismatch"


def test_case_without_tax_id_accepts_with_warning(client, samples):
    case_id = _new_case(client, None)
    r = _upload(client, case_id, ETAX / samples[0]["xml"], kind="etax_invoice")
    assert r.status_code == 201, r.text
    assert any("เลขประจำตัวผู้เสียภาษี" in w for w in r.json()["parse_report"]["warnings"])


def test_xml_only_for_etax(client, samples):
    case_id = _new_case(client, KITTI_TAX_ID)
    r = _upload(client, case_id, ETAX / samples[0]["xml"], kind="statement")
    assert r.status_code == 422 and r.json()["code"] == "not_a_pdf"


# ---- scanned / photographed invoices ------------------------------------------------------

def test_photo_invoice_is_read_by_ocr(samples):
    import hashlib

    from app.ocr.images import image_to_pdf
    from app.ocr.sandbox import SandboxOcrProvider
    from app.parsers.etax import parse_etax_words

    s = samples[2]
    data = (ETAX / s["photo"]).read_bytes()
    pages = SandboxOcrProvider().analyze(image_to_pdf(data), hashlib.sha256(data).hexdigest()).pages
    inv, ref = parse_etax_words(pages, source="scan_ocr"), parse_etax_xml(_xml(s))
    for f in ("invoice_no", "issue_date", "seller_tax_id", "buyer_name", "subtotal", "vat", "total"):
        assert getattr(inv, f) == getattr(ref, f), f
    assert inv.confidence["total"] < 0.5 <= inv.confidence["invoice_no"]  # the total is smudged


def test_uncertain_photo_invoice_is_held_until_a_ca_checks_it(client, truth, samples):
    from app.services import ocr_review
    from tests.helpers import SME

    s = samples[2]
    case_id = _new_case(client, KITTI_TAX_ID)
    assert _upload(client, case_id, GENERATED / truth["accounts"][s["account"]]["file"]).status_code == 201
    with open(ETAX / s["photo"], "rb") as f:
        r = client.post(f"/api/cases/{case_id}/documents", files={"file": (s["photo"], f, "image/jpeg")})
    assert r.status_code == 201, r.text
    doc = r.json()
    rep = doc["parse_report"]
    assert doc["kind"] == "etax_invoice" and rep["source"] == "scan_ocr" and rep["low_confidence"] == ["total"]
    assert rep["amounts"]["total"] == s["total"] and rep["ocr"]["provider"].startswith("sandbox")

    client.post(f"/api/cases/{case_id}/analysis")
    link = next(d for d in client.get(f"/api/cases/{case_id}/documents").json() if d["id"] == doc["id"])["invoice"]
    assert link["status"] == "held_review" and link["review_status"] == "pending"
    assert _receipt(client, case_id, s)["tier"] != "T1_golden"  # an unchecked OCR total verifies nothing
    with SessionLocal() as db:
        assert ocr_review.pending_documents(db, case_id) == 1  # and it blocks signing the memo

    url = f"/api/cases/{case_id}/invoices/{link['invoice_id']}/review"
    assert client.post(url, json={"action": "confirm", "reason": "สั้น"}).status_code == 422
    with _client_as(SME) as sme:
        assert sme.post(url, json={"action": "confirm", "reason": "ผู้กู้พยายามยืนยันเอง"}).status_code in (403, 404)
    r = client.post(url, json={"action": "confirm", "reason": "ตรวจภาพถ่ายแล้ว ยอดรวมทั้งสิ้นชัดเจนตรงกับที่อ่านได้"})
    assert r.status_code == 200, r.text
    link = next(d for d in client.get(f"/api/cases/{case_id}/documents").json() if d["id"] == doc["id"])["invoice"]
    assert link["status"] == "matched" and link["review_status"] == "confirmed"
    assert _receipt(client, case_id, s)["tier"] == "T1_golden"
    with SessionLocal() as db:
        assert ocr_review.pending_documents(db, case_id) == 0


def _client_as(headers):
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app, headers=headers)
