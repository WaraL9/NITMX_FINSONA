"""Credit-memo narrative (E7-04) and cash-pattern explanation (E7-03).

The LLM writes Thai prose using placeholders such as {{safe_limit}} for EVERY figure,
ratio, percentage or date. We then:
  1. reject any output containing digits (Arabic or Thai) outside placeholders,
  2. reject unknown placeholders,
  3. substitute the engine's own formatted values.
So no number in the memo can come from the model. If the LLM is unavailable or its
output fails validation, a deterministic Thai template is used instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.ai import gateway

PLACEHOLDER = re.compile(r"\{\{([a-z_][a-z0-9_]*)\}\}")
DIGIT = re.compile(r"[0-9๐-๙]")

SYSTEM = """คุณเป็นผู้ช่วยเขียนบันทึกวิเคราะห์สินเชื่อ (Credit Memo) ภาษาไทยให้เจ้าหน้าที่วิเคราะห์สินเชื่อของธนาคาร
เขียนด้วยน้ำเสียงเป็นกลาง กระชับ แบบรายงานวิชาชีพ ห้ามแต่งข้อเท็จจริงเพิ่ม ใช้เฉพาะข้อเท็จจริงที่ให้มา

กฎบังคับเรื่องตัวเลข:
- ห้ามพิมพ์ตัวเลขใด ๆ (ทั้งเลขอารบิกและเลขไทย) ในข้อความโดยเด็ดขาด
- ทุกจำนวนเงิน อัตราส่วน ร้อยละ จำนวนครั้ง หรือวันที่ ต้องเขียนเป็นตัวแทนในรูปแบบ {{ชื่อ}} ตามรายการที่ให้มาเท่านั้น
- ห้ามสร้างชื่อตัวแทนใหม่ที่ไม่อยู่ในรายการ
- ห้ามให้ความเห็นว่าควรอนุมัติหรือปฏิเสธ — การตัดสินใจเป็นของเจ้าหน้าที่สินเชื่อ"""

NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {"paragraphs": {"type": "array", "items": {"type": "string"}}},
    "required": ["paragraphs"],
    "additionalProperties": False,
}


class NarrativeInvalid(ValueError):
    pass


def fill(text: str, facts: dict[str, str]) -> str:
    """Validate an LLM draft and substitute engine values into its placeholders."""
    outside = PLACEHOLDER.sub("", text)
    if DIGIT.search(outside):
        raise NarrativeInvalid("draft contains digits outside placeholders")
    unknown = sorted({k for k in PLACEHOLDER.findall(text) if k not in facts})
    if unknown:
        raise NarrativeInvalid(f"unknown placeholders: {', '.join(unknown)}")
    return PLACEHOLDER.sub(lambda m: facts[m.group(1)], text)


def baht(d: Decimal) -> str:
    return f"{d:,.0f} บาท"


def millions(d: Decimal) -> str:
    return f"{d / Decimal(1_000_000):,.2f} ล้านบาท"


@dataclass
class Narrative:
    text: str
    source: str  # "llm" | "llm-cache" | "template"
    note: str | None = None


def _template(f: dict[str, str], flags: dict[str, bool]) -> list[str]:
    p1 = (f"{{{{company}}}} ขอสินเชื่อ {{{{requested}}}} จากสเตทเมนต์ {{{{accounts}}}} บัญชี ยอดเงินเข้าดิบ {{{{gross_inflow}}}} "
          f"เมื่อตัดเงินโอนวนระหว่างบัญชีตนเอง {{{{loops}}}} ({{{{loop_count}}}} วงจร) เงินจากเจ้าของและครอบครัว {{{{owner_inflow}}}} "
          f"และรายการที่ยังไม่มีเอกสารรองรับ {{{{unverified}}}} คงเหลือรายได้จากการค้าที่ยืนยันแล้ว {{{{verified_revenue}}}} "
          f"โดย {{{{t1_share}}}} ยืนยันด้วยใบแจ้งหนี้อิเล็กทรอนิกส์บนโครงข่าย PromptBiz")
    p2 = (f"หลังหักต้นทุนดำเนินงาน กระแสเงินสดสุทธิเฉลี่ย {{{{cfo_monthly}}}} ต่อเดือน มีภาระหนี้เดิม {{{{existing_debt}}}} ต่อเดือน "
          f"ที่วงเงินตามคำขอ DSCR เท่ากับ {{{{dscr_request}}}} ต่ำกว่าเกณฑ์ขั้นต่ำ {{{{min_dscr}}}} "
          f"วงเงินสูงสุดที่ยังรักษา DSCR ตามเป้าหมาย {{{{target_dscr}}}} คือ {{{{safe_limit}}}}")
    if flags.get("structure"):
        p2 += (f" ระบบเสนอโครงสร้างวงเงินระยะยาว {{{{safe_limit}}}} ควบคู่วงเงินหมุนเวียน Trade Line {{{{trade_line}}}} "
               f"ผูกการชำระคืนกับใบแจ้งหนี้บน PromptBiz รวม {{{{structure_total}}}}")
    p3 = ""
    if flags.get("cash_pattern"):
        p3 += (f"การถอนเงินสด {{{{cash_count}}}} ครั้ง รวม {{{{cash_total}}}} เกิดขึ้นสม่ำเสมอในวัน{{{{cash_days}}}} ช่วงเช้า "
               f"สอดคล้องกับรอบจ่ายค่าแรงและซื้อวัสดุหน้างานของธุรกิจรับเหมา จึงนับเป็นต้นทุนดำเนินงานจริง ")
    if flags.get("liveness"):
        p3 += "ประวัติชำระค่าไฟฟ้า ค่าน้ำ และค่าเช่าตรงเวลาต่อเนื่อง ยืนยันการเปิดดำเนินกิจการจริง "
    if flags.get("haircut"):
        p3 += f"พบการชำระค่าสาธารณูปโภคล่าช้า ระบบจึงปรับลดกระแสเงินสดที่ใช้คำนวณวงเงินลง {{{{haircut_pct}}}} "
    if flags.get("accepted"):
        p3 += f"เจ้าหน้าที่สินเชื่อได้ใช้ดุลยพินิจรับรองรายได้เพิ่มเติม {{{{accepted}}}} พร้อมบันทึกเหตุผลในระบบตรวจสอบย้อนหลัง "
    paras = [p1, p2]
    if p3:
        paras.append(p3.strip())
    return paras


def draft(db: Session, facts: dict[str, str], flags: dict[str, bool], case_id: int | None = None) -> Narrative:
    """LLM draft when available (validated, numbers injected), else the template."""
    user = (
        "ข้อเท็จจริงจากระบบคำนวณ (ใช้ชื่อตัวแทนเท่านั้น ห้ามใส่ตัวเลขเอง):\n"
        + "\n".join(f"- {{{{{k}}}}} = {v}" for k, v in sorted(facts.items()))
        + "\n\nประเด็นที่ควรกล่าวถึง: " + ", ".join(k for k, on in sorted(flags.items()) if on)
        + "\n\nเขียนบทสรุปผลการวิเคราะห์ 2-3 ย่อหน้าสั้น ๆ สำหรับบันทึกเสนอคณะกรรมการสินเชื่อ"
    )
    try:
        res = gateway.complete_json(db, "memo_narrative", SYSTEM, user, NARRATIVE_SCHEMA, max_tokens=2000,
                                    case_id=case_id)
        paragraphs = [p.strip() for p in res.data.get("paragraphs", []) if p.strip()]
        if not paragraphs:
            raise NarrativeInvalid("empty draft")
        text = "\n\n".join(fill(p, facts) for p in paragraphs)
        return Narrative(text, "llm" if res.source == "live" else "llm-cache")
    except (gateway.LLMUnavailable, NarrativeInvalid) as e:
        text = "\n\n".join(fill(p, facts) for p in _template(facts, flags))
        return Narrative(text, "template", str(e))
