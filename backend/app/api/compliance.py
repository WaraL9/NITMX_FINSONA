"""Compliance status (E14-09): live checks, not static claims."""

from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth, storage
from app.ai import gateway
from app.ai.pii import mask
from app.api.deps import require_role
from app.config import settings
from app.db import get_db
from app.models import Case, Document, Evidence, User
from app.services import audit, consent

router = APIRouter(tags=["compliance"])

PII_SAMPLE = "โอนให้ นาย ทดสอบ ระบบ 081-234-5678 test@example.com บัญชี 123-4-56789-0"

# (control, status, detail). status: implemented | sandbox | planned
CONTROLS = [
    ("Human-in-the-loop decisions", "implemented", "ระบบไม่ปฏิเสธเอง ทุกการรับรอง/ตัดออก/ลงนามต้องมีเหตุผลของ CA"),
    ("Deterministic math (no AI numbers)", "implemented", "ตัวเลขทั้งหมดจากสูตรบัญชี AI เขียนได้เฉพาะถ้อยคำและถูกตรวจว่าไม่มีตัวเลข"),
    ("Pixel-level lineage", "implemented", "ทุกตัวเลขย้อนถึงบรรทัดและพิกัดบนเอกสารต้นฉบับ พร้อมตรวจ SHA-256"),
    ("Immutable audit log", "implemented", "ลูกโซ่ SHA-256 ตรวจการแก้ไขย้อนหลังได้ ส่งออก CSV ให้ฝ่ายตรวจสอบ"),
    ("Authentication & least privilege", "implemented", "PBKDF2, session ลงนาม HMAC, จำกัดสิทธิ์ตามบทบาทและแฟ้ม, Auditor อ่านอย่างเดียว"),
    ("Purpose-based consent (PDPA)", "implemented", "ดึงข้อมูลภายนอกได้เฉพาะวัตถุประสงค์ที่ยินยอม เพิกถอนแล้วลบข้อมูลที่ดึงมา"),
    ("PII masking before AI", "implemented", "ปิดบังเลขบัตร เบอร์โทร อีเมล เลขบัญชี ชื่อบุคคล ก่อนส่ง และบันทึกสิ่งที่ AI เห็น"),
    ("No customer data used to train models", "implemented", "ส่งเฉพาะข้อความที่ปิดบังแล้วเพื่อสร้างคำตอบ ไม่มีการฝึกโมเดลด้วยข้อมูลลูกค้า"),
    ("Encryption at rest", "implemented", "ไฟล์ทุกไฟล์เข้ารหัส Fernet (AES + HMAC) ตรวจจับไฟล์ถูกแก้"),
    ("Deletion on request", "implemented", "ลบแฟ้มและไฟล์ทั้งหมด โดยบันทึกการลบไว้ในลูกโซ่ตรวจสอบ"),
    ("Fairness & protected attributes", "implemented", "ไม่มีตัวแปรเพศ ศาสนา เชื้อชาติ ภูมิลำเนา; ตรวจกฎ 4/5 ตามขนาดธุรกิจ"),
    ("Responsible lending sizing", "implemented", "วงเงินจาก DSCR/DSR ตามนโยบายที่ตั้งค่าได้และมีประวัติเวอร์ชัน"),
    ("OCR confidence gating", "implemented", "ตัวเลขจากเอกสารสแกนที่ความมั่นใจ < 50% หรือยอดคงเหลือไม่ต่อเนื่อง ไม่ถูกนับจนกว่า CA ตรวจทานกับภาพต้นฉบับ"),
    ("OCR provider (Azure AI Document Intelligence)", "sandbox", "Sandbox เล่นซ้ำผล OCR ที่บันทึกไว้ของเอกสารเดโม; adapter Azure พร้อมใช้เมื่อมีคีย์"),
    ("LOS hand-off (loan origination)", "sandbox", "ส่งผลตัดสินที่ลงนามแล้วพร้อมลายนิ้วมือเอกสาร แบบ idempotent — ไม่มีข้อมูลรายธุรกรรมออกจากระบบ"),
    ("PromptBiz / utility / dStatement integration", "sandbox", "เชื่อมผ่าน Sandbox Connector ที่มี interface เดียวกับของจริง"),
    ("Encryption in transit (TLS 1.3)", "planned", "ต้องติดตั้งหลัง reverse proxy/Front Door บนคลาวด์ของธนาคาร"),
    ("Data residency — Azure Thailand region", "planned", "ขณะนี้รันบนเครื่องพัฒนา; เป้าหมายคือ tenant ของธนาคารในประเทศไทย"),
    ("Keys in bank-controlled Key Vault", "planned", "ขณะนี้เก็บ key ในไฟล์ที่ git ไม่ติดตาม"),
    ("ISO 27001 / SOC 2 controls", "planned", "อาศัยการรับรองของผู้ให้บริการคลาวด์ + ขั้นตอนของธนาคาร"),
]


@router.get("/api/compliance")
def compliance(db: Session = Depends(get_db), _: User = Depends(require_role("CA", "AUDITOR"))) -> dict:
    files = [Path(d.storage_path) for d in db.scalars(select(Document))] + \
            [Path(e.storage_path) for e in db.scalars(select(Evidence))]
    present = [p for p in files if p.exists()]
    encrypted = sum(storage.is_encrypted(p) for p in present)
    chain = audit.verify(db)
    cases = db.scalars(select(Case)).all()
    grants = [consent.current(db, c.id) for c in cases]
    masked = mask(PII_SAMPLE)
    return {
        "controls": [{"control": c, "status": s, "detail": d} for c, s, d in CONTROLS],
        "checks": {
            "encryption": {"files": len(present), "encrypted": encrypted, "ok": encrypted == len(present)},
            "audit_chain": {"ok": chain.ok, "entries": chain.entries, "first_bad_id": chain.first_bad_id},
            "consent": {"cases": len(cases),
                        "with_credit_assessment": sum(bool(g["credit_assessment"] and g["credit_assessment"].granted)
                                                      for g in grants)},
            "pii_masking": {"sample": PII_SAMPLE, "masked": masked.text, "counts": masked.counts,
                            "ok": all(k in masked.counts for k in ("person_name", "phone", "email", "account_number"))},
            "auth": {"token_ttl_hours": auth.TOKEN_TTL // 3600, "lockout_after_failures": auth.MAX_FAILURES,
                     "demo_mode": settings.demo_mode},
            "llm": gateway.status(),
            "connector_mode": settings.connector_mode,
        },
    }
