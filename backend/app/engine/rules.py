"""Deterministic tagging rules (E4-04, E4-05, E4-07, E4-08).

Each rule returns (tag, reason). The reason is shown to the analyst, so it is written in
Thai and names the evidence. First matching rule wins.
"""

from __future__ import annotations

import re

from app.engine.types import ETxn
from app.core.i18n import th

INDIVIDUAL_PREFIX = re.compile(r"^(นางสาว|นาง|นาย|น\.ส\.|ด\.ช\.|ด\.ญ\.)\s*")
COMPANY_MARKERS = ("บจก.", "บริษัท", "หจก.", "ห้างหุ้นส่วน", "บมจ.", "ร้าน")

# Business cost categories — all count as operating costs.
COST_TAGS = {"payroll", "rent", "utilities", "bank_fee", "cash_withdrawal", "supplier_payment", "other_expense"}

HOUSEHOLD_KEYWORDS = ("ค่าเทอม", "ส่วนบุคคล", "ค่าใช้จ่ายบ้าน", "ส่วนตัว")
DEBT_RE = re.compile(r"สินเชื่อ|เงินกู้|ค่างวดสินเชื่อ|LOAN", re.IGNORECASE)

DEBIT_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("payroll", re.compile(r"PAYROLL|เงินเดือน"), th("จ่ายเงินเดือนพนักงาน")),
    ("rent", re.compile(r"ค่าเช่า"), th("ค่าเช่าสถานประกอบการ")),
    ("utilities", re.compile(r"ค่าไฟฟ้า|ค่าน้ำประปา|การไฟฟ้า|การประปา"), th("ค่าสาธารณูปโภค")),
    ("bank_fee", re.compile(r"ค่าธรรมเนียม"), th("ค่าธรรมเนียมธนาคาร")),
    ("cash_withdrawal", re.compile(r"ถอนเงินสด"), th("ถอนเงินสด (นับเป็นต้นทุนดำเนินงาน เช่น ค่าแรง/วัสดุหน้างาน)")),
]


def is_individual(name: str | None) -> bool:
    return bool(name) and bool(INDIVIDUAL_PREFIX.match(name.strip())) and not name.startswith(COMPANY_MARKERS)


def surname(name: str | None) -> str | None:
    if not name:
        return None
    rest = INDIVIDUAL_PREFIX.sub("", name.strip())
    parts = rest.split()
    return parts[-1] if len(parts) >= 2 else None


def normalize_party(name: str | None) -> str:
    """Normalise a counterparty name for matching: drop legal-form words and spacing."""
    if not name:
        return ""
    s = name
    for w in ("บริษัท", "บจก.", "จำกัด", "(มหาชน)", "หจก.", "ห้างหุ้นส่วนจำกัด", "Co., Ltd.", "Co.,Ltd."):
        s = s.replace(w, "")
    return re.sub(r"\s+", "", s).lower()


def is_family(name: str | None, family_surnames: set[str]) -> bool:
    return is_individual(name) and surname(name) in family_surnames


def tag_company_debit(t: ETxn, family_surnames: set[str]) -> tuple[str, str]:
    text = f"{t.description} {t.counterparty_name or ''}"
    if any(k in text for k in HOUSEHOLD_KEYWORDS) or is_family(t.counterparty_name, family_surnames):
        return "household", th("ค่าใช้จ่ายครัวเรือน/ส่วนตัวของเจ้าของ — แยกออกจากต้นทุนธุรกิจ (ถือเป็นเงินถอนของเจ้าของ)")
    if t.code == "LOAN" or DEBT_RE.search(text):
        return "debt_service", th("ผ่อนชำระหนี้เดิม — นับเป็นภาระหนี้ ไม่ใช่ต้นทุนดำเนินงาน")
    for tag, rx, reason in DEBIT_RULES:
        if rx.search(text) or (tag == "bank_fee" and t.code == "FEE") or (tag == "cash_withdrawal" and t.code == "CW"):
            return tag, reason
    if t.counterparty_name and not is_individual(t.counterparty_name):
        return "supplier_payment", th("จ่ายคู่ค้า/ซัพพลายเออร์")
    return "other_expense", th("รายจ่ายอื่น (นับเป็นต้นทุนเพื่อความระมัดระวัง)")


def tag_company_credit(t: ETxn, family_surnames: set[str]) -> tuple[str, str]:
    if is_family(t.counterparty_name, family_surnames):
        return "owner_injection", th(f"เงินโอนจากเจ้าของ/ครอบครัว ({t.counterparty_name}) — เป็นเงินทุน ไม่ใช่รายได้")
    if t.code == "PP-IN" or "พร้อมเพย์" in t.description:
        return "promptpay_receipt", th("รับชำระผ่านพร้อมเพย์")
    if t.code == "CD" or "ฝากเงินสด" in t.description:
        return "cash_deposit", th("ฝากเงินสดเข้าบัญชี")
    if t.counterparty_name:
        return "customer_receipt", th(f"รับโอนจาก {t.counterparty_name}")
    return "other_income", th("เงินเข้าอื่น ไม่ระบุที่มา")
