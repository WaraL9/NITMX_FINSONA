"""Encryption at rest (E14-05) and deletion (E14-08)."""

import hashlib
from pathlib import Path

import pytest

from app import storage
from app.config import settings
from app.db import SessionLocal
from app.models import Document


def test_uploaded_files_are_encrypted_on_disk(client, seeded_case_id, statement_path):
    with SessionLocal() as db:
        doc = db.query(Document).filter(Document.case_id == seeded_case_id).first()
    raw = Path(doc.storage_path).read_bytes()
    assert raw.startswith(storage.MAGIC) and b"%PDF" not in raw[:64]
    served = client.get(f"/api/documents/{doc.id}/file").content
    assert served.startswith(b"%PDF-") and hashlib.sha256(storage.read(Path(doc.storage_path))).hexdigest() == doc.sha256


def test_tampered_file_is_detected(tmp_path):
    p = tmp_path / "x.bin"
    storage.write(p, b"hello")
    data = bytearray(p.read_bytes())
    data[-5] ^= 0xFF
    p.write_bytes(bytes(data))
    with pytest.raises(storage.StorageCorrupt):
        storage.read(p)


def test_delete_case_removes_files_and_logs(client, statement_path):
    cid = client.post("/api/cases", json={"company_name": "ลบทดสอบ", "industry": "x", "business_age_years": 1,
                                          "requested_amount": "100000", "purpose": "x", "tenor_months": 12,
                                          "annual_rate": "0.07"}).json()["id"]
    with open(statement_path("SCB_SAV"), "rb") as f:
        up = client.post(f"/api/cases/{cid}/documents", files={"file": ("s.pdf", f, "application/pdf")}).json()
    folder = settings.storage_dir / f"case_{cid}"
    assert folder.exists()
    assert client.request("DELETE", f"/api/cases/{cid}", json={"reason": "สั้น"}).status_code == 422
    r = client.request("DELETE", f"/api/cases/{cid}", json={"reason": "ลูกค้าขอลบข้อมูลตาม PDPA มาตรา 33"})
    assert r.status_code == 200 and r.json()["documents"] == 1
    assert not folder.exists()
    assert client.get(f"/api/cases/{cid}").status_code == 404
    with SessionLocal() as db:
        assert db.query(Document).filter(Document.case_id == cid).count() == 0
    log = client.get(f"/api/cases/{cid}/audit")
    assert log.status_code == 404  # case gone; the global chain still holds the entry
    assert client.get("/api/audit/verify").json()["ok"] is True
    with SessionLocal() as db:
        from app.models import AuditEntry

        entry = db.query(AuditEntry).filter(AuditEntry.action == "case_deleted", AuditEntry.case_id == cid).one()
        assert entry.before["documents"][0]["sha256"] == up["sha256"]
