"""LLM help for transactions the rules could not label (E7-02).

Only rows the rules left as `other_expense` are sent, and the model may only choose
among business-cost categories. Every cost category counts toward operating costs the
same way, so a suggestion changes the label and explanation shown to the analyst but
can never change a number. Low-confidence answers are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai import gateway
from app.engine.rules import COST_TAGS

MIN_CONFIDENCE = 0.7
ALLOWED = sorted(COST_TAGS)

SYSTEM = """คุณช่วยจัดหมวดรายการจ่ายเงินในสเตทเมนต์ธนาคารของธุรกิจ SME ไทย
เลือกหมวดจากรายการที่กำหนดเท่านั้น ตอบตามข้อมูลที่เห็น ถ้าไม่แน่ใจให้ความเชื่อมั่นต่ำ
ห้ามคำนวณหรือระบุจำนวนเงินในเหตุผล"""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "tag": {"type": "string", "enum": ALLOWED},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": ["id", "tag", "confidence", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


@dataclass
class Suggestion:
    txn_id: int
    tag: str
    confidence: float
    rationale: str


def suggest(db: Session, rows: list[tuple[int, str, str | None]]) -> list[Suggestion]:
    """rows: (txn id, description, counterparty). Returns accepted suggestions only."""
    if not rows:
        return []
    user = "หมวดที่เลือกได้: " + ", ".join(ALLOWED) + "\n\nรายการ:\n" + "\n".join(
        f"- id={tid} รายละเอียด: {desc} | คู่โอน: {cp or '-'}" for tid, desc, cp in rows)
    try:
        res = gateway.complete_json(db, "txn_tagging", SYSTEM, user, SCHEMA, max_tokens=4000)
    except gateway.LLMUnavailable:
        return []
    ids = {tid for tid, _, _ in rows}
    out = []
    for it in res.data.get("items", []):
        if it.get("id") in ids and it.get("tag") in COST_TAGS and float(it.get("confidence", 0)) >= MIN_CONFIDENCE:
            out.append(Suggestion(it["id"], it["tag"], float(it["confidence"]), str(it.get("rationale", ""))[:300]))
    return out
