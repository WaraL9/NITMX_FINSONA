"""OCR path and human review queue (E2-08, E2-09, E2-10) on seeded case 2 (Somjai, scanned SCB statement)."""

import io
import json
from decimal import Decimal

import pytest
from reportlab.pdfgen import canvas

from app.config import settings
from app.db import SessionLocal
from app.models import Case, Document, Transaction
from app.services import ocr_review
from app.synth.cases import somjai
from tests.helpers import CA, RM

SCB = "scan_SCB_SCB_SAV.pdf"


@pytest.fixture(scope="module")
def somjai_id(seeded_case_id):
    with SessionLocal() as db:
        return db.query(Case).filter(Case.tax_id == somjai().case.tax_id).one().id


@pytest.fixture()
def fresh(client):
    client.post("/api/demo/reset")  # other tests may have resolved rows already
    return client


def _scan(db, case_id) -> Document:
    return db.query(Document).filter(Document.case_id == case_id, Document.filename == SCB).one()


def _recording(doc: Document) -> dict:
    path = settings.data_dir / "generated" / "ocr_recorded" / f"{doc.sha256}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_scan_goes_through_ocr_and_is_gated(fresh, somjai_id):
    with SessionLocal() as db:
        doc = _scan(db, somjai_id)
        assert doc.parser.startswith("ocr:sandbox")
        ocr = doc.parse_report["ocr"]
        assert ocr["words"] > 1000 and 0.9 < ocr["mean_confidence"] < 1
        assert ocr["review_pending"] == ocr_review.pending_count(db, somjai_id) > 0
        rows = db.query(Transaction).filter(Transaction.document_id == doc.id).all()
        assert all(t.ocr_fields for t in rows)
        # every recorded misread lands in the queue
        pending_tops = {(t.page_id, round(t.bbox_y0 + 2)) for t in rows if t.review_status == "pending"}
        page_ids = {p.page_no: p.id for p in doc.pages}
        for m in _recording(doc)["truth"]:
            assert (page_ids[m["page_no"]], round(m["top"])) in pending_tops, m
    q = fresh.get(f"/api/cases/{somjai_id}/ocr-review?status=pending").json()
    assert q and all(r["review_status"] == "pending" and r["bbox"] and r["page_no"] for r in q)
    assert all(any(x.startswith(("low_confidence:", "balance_break")) for x in r["review_reasons"]) for r in q)


def test_memo_sign_blocked_while_rows_pending(fresh, somjai_id):
    body = {"recommendation": "decline", "reason": "ทดสอบการลงนามระหว่างรอตรวจ OCR"}
    fresh.post(f"/api/cases/{somjai_id}/memo/regenerate")
    r = fresh.post(f"/api/cases/{somjai_id}/memo/sign", json=body)
    assert r.status_code == 409 and "OCR" in r.text


def test_corrections_restore_exact_figures(fresh, somjai_id):
    with SessionLocal() as db:
        doc = _scan(db, somjai_id)
        page_no = {p.id: p.page_no for p in doc.pages}
        rows = db.query(Transaction).filter(Transaction.document_id == doc.id).all()
        fixes: dict[int, dict[str, str]] = {}
        for m in _recording(doc)["truth"]:
            t = next(t for t in rows if page_no[t.page_id] == m["page_no"] and abs(t.bbox_y0 + 2 - m["top"]) < 1)
            read = Decimal(m["read"].replace(",", ""))
            field = next(f for f in ("debit", "credit", "balance") if getattr(t, f) == read)
            fixes.setdefault(t.id, {})[field] = m["actual"].replace(",", "")
    assert fixes, "the recording should contain at least one misread"

    for txn_id, values in fixes.items():
        r = fresh.post(f"/api/cases/{somjai_id}/ocr-review/{txn_id}",
                       json={"action": "correct", **values, "reason": "แก้ตามภาพสแกนต้นฉบับ ตัวเลขชัดเจน"})
        assert r.status_code == 200, r.text
        assert r.json()["changed"] is True
    for row in fresh.get(f"/api/cases/{somjai_id}/ocr-review?status=pending").json():
        r = fresh.post(f"/api/cases/{somjai_id}/ocr-review/{row['id']}", json={"action": "confirm"})
        assert r.status_code == 200, r.text
    assert r.json()["pending_left"] == 0

    sc = somjai()
    w = fresh.get(f"/api/cases/{somjai_id}/analysis").json()["waterfall"]
    assert Decimal(w["gross_raw_inflow"]) == sc.revenue.gross_raw_inflow
    assert Decimal(w["own_account_loops"]) == sc.revenue.own_account_loops
    with SessionLocal() as db:
        assert _scan(db, somjai_id).parse_report["continuity_ok"] is True
    audit = fresh.get(f"/api/cases/{somjai_id}/audit").json()
    assert sum(e["action"] == "ocr_review" for e in audit) >= len(fixes)


def test_review_validation(fresh, somjai_id):
    row = fresh.get(f"/api/cases/{somjai_id}/ocr-review?status=pending").json()[0]
    url = f"/api/cases/{somjai_id}/ocr-review/{row['id']}"
    assert fresh.post(url, json={"action": "confirm"}, headers=RM).status_code == 403
    assert fresh.post(url, json={"action": "correct", "credit": "1.00"}).status_code == 422  # no reason
    both = {"action": "correct", "debit": "5.00", "credit": "5.00", "reason": "ทดสอบค่าที่ขัดแย้งกัน"}
    assert fresh.post(url, json=both).status_code == 422
    kitti_row = 1  # a digital row cannot be "OCR-reviewed"
    assert fresh.post(f"/api/cases/1/ocr-review/{kitti_row}", json={"action": "confirm"}).status_code == 422


def test_confident_misread_is_caught_by_balance_check(fresh, somjai_id):
    """A wrong figure read with HIGH confidence still surfaces through the running balance."""
    with SessionLocal() as db:
        doc = _scan(db, somjai_id)
        rows = db.query(Transaction).filter(Transaction.document_id == doc.id).order_by(Transaction.row_index).all()
        clean = {t.row_index for t in rows if t.review_status is None}
        victim = next(t for t in rows if t.row_index in clean and t.row_index + 1 in clean
                      and t.row_index - 1 in clean and t.credit > 0 and t.row_index > 5)
        victim.credit += Decimal("1000.00")
        victim.balance += Decimal("1000.00")  # printed balance read consistently... for this row only
        ocr_review.flag_document(db, doc)
        nxt = next(t for t in rows if t.row_index == victim.row_index + 1)
        for t in (victim, nxt):  # the break is at nxt; the culprit is victim — both are shown
            assert t.review_status == "pending" and "balance_break" in t.review_reasons
        db.rollback()


def test_scan_without_recording_needs_live_ocr(fresh, somjai_id):
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.rect(50, 50, 200, 200, fill=1)  # an image-like page with no text layer
    c.showPage()
    c.save()
    r = fresh.post(f"/api/cases/{somjai_id}/documents", files={"file": ("photo.pdf", buf.getvalue(), "application/pdf")},
                   data={"kind": "statement"}, headers=CA)
    assert r.status_code in (415, 422), r.text
    assert "OCR" in r.text


def test_uncertain_amounts_are_held_out_and_lineage_still_sums(fresh, somjai_id):
    a = fresh.get(f"/api/cases/{somjai_id}/analysis").json()
    held = a["ocr_held"]
    assert held["rows"] > 0 and Decimal(held["credit"]) > 0
    for metric, figure in (("gross_raw_inflow", a["waterfall"]["gross_raw_inflow"]),
                           ("verified_operating_revenue", a["waterfall"]["verified_operating_revenue"])):
        page = fresh.get(f"/api/cases/{somjai_id}/transactions", params={"metric": metric, "limit": 1}).json()
        assert page["sum_credit"] == figure, metric
    # held rows are visible and explained, but in no figure
    rows = fresh.get(f"/api/cases/{somjai_id}/transactions", params={"tag": "ocr_pending", "limit": 100}).json()
    assert rows["total"] == held["rows"] and rows["sum_credit"] == held["credit"]
