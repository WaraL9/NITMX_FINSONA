"""What evidence would verify a Watchlist item (E7-05).

For each open Watchlist item the LLM suggests the documents a CA should ask for (e.g. a
fit-out contract for instalment one) and one question the RM can put to the customer.
It is advice only: it never changes a tier or a figure.

Numbers: the model may not write any. Amounts, dates and names are {{amount}}, {{date}}
and {{counterparty}} placeholders, filled by the engine; an item whose text has a digit
outside a placeholder (or an unknown placeholder) falls back to the rule-based template,
as does every item when no LLM is available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.ai import gateway
from app.ai.narrative import NarrativeInvalid, fill
from app.engine.rules import is_individual

MAX_EVIDENCE = 3

SYSTEM = """คุณช่วยเจ้าหน้าที่วิเคราะห์สินเชื่อ SME ของธนาคารไทยตัดสินใจเรื่องเงินเข้าที่ยังไม่มีเอกสารยืนยัน
สำหรับแต่ละรายการ ให้เสนอเอกสารหลักฐาน 1-3 อย่างที่จะพิสูจน์ได้ว่าเป็นรายได้จากการค้าจริง
ให้เจาะจงกับประเภทธุรกิจและข้อความในรายการ (เช่น สัญญาว่าจ้างงานตกแต่งคลินิกงวดแรก พร้อมใบตรวจรับงาน)
พร้อมเหตุผลสั้น ๆ และคำถามหนึ่งข้อที่ RM ใช้ถามลูกค้าได้ทันที

กฎบังคับ:
- ห้ามพิมพ์ตัวเลขใด ๆ (ทั้งเลขอารบิกและเลขไทย) เขียนลำดับเป็นคำ เช่น งวดแรก งวดที่สอง
- จำนวนเงิน วันที่ และชื่อคู่โอน ให้ใช้ตัวแทน {{amount}} {{date}} {{counterparty}} เท่านั้น
- แบบแสดงรายการภาษีมูลค่าเพิ่ม ให้เขียนเป็น {{pp30}}
- ห้ามสรุปว่ารายการนี้เป็นหรือไม่เป็นรายได้ — การตัดสินเป็นของเจ้าหน้าที่"""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"document": {"type": "string"}, "why": {"type": "string"}},
                            "required": ["document", "why"],
                            "additionalProperties": False,
                        },
                    },
                    "question": {"type": "string"},
                },
                "required": ["id", "evidence", "question"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


@dataclass
class HintInput:
    item_id: int
    description: str
    counterparty: str | None
    code: str
    credit: Decimal
    posted_at: datetime
    system_note: str


@dataclass
class Hint:
    source: str  # live | cache | template
    evidence: list[dict[str, str]] = field(default_factory=list)  # [{document, why}], numbers filled in
    question: str = ""
    model: str | None = None

    def to_json(self) -> dict:
        return {"source": self.source, "evidence": self.evidence, "question": self.question, "model": self.model}


def _facts(x: HintInput) -> dict[str, str]:
    d = x.posted_at.date()
    return {"amount": f"{x.credit:,.2f} บาท", "date": f"{d.day:02d}/{d.month:02d}/{d.year + 543}",
            "counterparty": x.counterparty or "ผู้โอน", "pp30": "ภ.พ.30"}


def _fill(text: str, facts: dict[str, str]) -> str:
    # The form's name contains digits; accept it as a fixed term rather than reject the text.
    return fill(text.replace("ภ.พ.30", "{{pp30}}"), facts)


def template(x: HintInput) -> Hint:
    """Rule-based hints — what an experienced CA would ask for, by the kind of inflow."""
    if x.code == "CD" or "ฝากเงินสด" in x.description:
        ev = [("ใบเสร็จรับเงิน/ใบส่งของที่ออกให้ลูกค้าซึ่งชำระเป็นเงินสด {{amount}}",
               "เงินสดไม่มีร่องรอยผู้จ่าย ต้องมีเอกสารการขายที่ตรงยอดและวันที่ {{date}}"),
              ("สมุดบันทึกเงินสด/รายงานขายประจำวันช่วงก่อนวันที่ {{date}}",
               "แสดงว่าเงินสดสะสมมาจากการขายจริง ไม่ใช่เงินกู้หรือเงินส่วนตัว")]
        q = "เงินสด {{amount}} ที่ฝากวันที่ {{date}} มาจากการขายให้ลูกค้ารายใด ขอใบเสร็จหรือใบส่งของประกอบ"
    elif x.counterparty and is_individual(x.counterparty):
        ev = [("ใบเสนอราคา/สัญญาว่าจ้างที่ลงนามโดย {{counterparty}}",
               "ผู้โอนเป็นบุคคลธรรมดา ต้องยืนยันว่าเป็นลูกค้าที่ซื้อสินค้าหรือบริการจริง"),
              ("ใบกำกับภาษีหรือใบเสร็จที่ออกให้ {{counterparty}} ตามยอด {{amount}}",
               "ยืนยันว่ารายการถูกบันทึกเป็นรายได้ของกิจการ"),
              ("ภาพถ่ายหน้างานหรือใบตรวจรับงาน", "ยืนยันว่างานส่งมอบแล้ว ไม่ใช่เงินยืมจากคนรู้จัก")]
        q = "ยอด {{amount}} จาก {{counterparty}} วันที่ {{date}} เป็นค่างานอะไร ขอใบเสนอราคาหรือสัญญาที่ลูกค้าลงนาม"
    else:
        ev = [("สัญญาว่าจ้าง/ใบสั่งซื้อจาก {{counterparty}}", "ยืนยันที่มาของยอด {{amount}} ว่าเป็นการค้าตามปกติ"),
              ("ใบกำกับภาษีที่ออกให้ {{counterparty}}", "ไม่พบในใบแจ้งหนี้ PromptBiz หรือยอดขายที่ยื่น ภ.พ.30")]
        q = "ยอด {{amount}} จาก {{counterparty}} วันที่ {{date}} เป็นค่าสินค้าหรือบริการงานใด ขอสัญญาหรือใบกำกับภาษีประกอบ"
    f = _facts(x)
    return Hint("template", [{"document": _fill(d, f), "why": _fill(w, f)} for d, w in ev], _fill(q, f))


def _from_llm(raw: dict, x: HintInput, source: str, model: str) -> Hint:
    f = _facts(x)
    evidence = [{"document": _fill(str(e["document"]), f), "why": _fill(str(e["why"]), f)}
                for e in raw.get("evidence", [])[:MAX_EVIDENCE]]
    if not evidence:
        raise NarrativeInvalid("no evidence suggested")
    return Hint(source, evidence, _fill(str(raw.get("question", "")), f), model)


def suggest(db: Session, items: list[HintInput], industry: str, case_id: int | None = None) -> dict[int, Hint]:
    """item id -> hint, for every item (template when the LLM is unavailable or its answer is invalid)."""
    if not items:
        return {}
    out = {x.item_id: template(x) for x in items}
    user = f"ประเภทธุรกิจของผู้กู้: {industry}\n\nรายการที่ต้องการหลักฐาน:\n" + "\n".join(
        f"- id={x.item_id} | รายละเอียด: {x.description} | คู่โอน: {x.counterparty or '-'} | "
        f"ข้อสังเกตของระบบ: {x.system_note}" for x in items)
    try:
        res = gateway.complete_json(db, "watchlist_evidence_hint", SYSTEM, user, SCHEMA, max_tokens=4000,
                                    case_id=case_id)
    except gateway.LLMUnavailable:
        return out
    by_id = {x.item_id: x for x in items}
    for raw in res.data.get("items", []):
        x = by_id.get(raw.get("id"))
        if x is None:
            continue
        try:
            out[x.item_id] = _from_llm(raw, x, res.source, res.model)
        except (NarrativeInvalid, KeyError, TypeError):
            pass  # keep the template for this item
    return out
