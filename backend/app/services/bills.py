"""Uploaded utility & rent bills in the alt-data rules (E2-14).

For each uploaded bill, at every analysis:
  * held_review         an OCR'd key field is still uncertain -> not used until a CA confirms it
  * paid date           printed on a receipt, else the statement debit that paid it (matched by
                        customer number or bill type, amount +-1.00, due-45..due+120 days)
  * corroborated        the utility connector has the same bill and agrees -> connector used
  * conflict            the connector has it but amount or paid date differ -> connector used,
                        the CA is told
  * payment_not_found   past due, no receipt and no bank payment. Not treated as unpaid (cash
                        at a counter is common) — left out of the rules and raised for a query
  * used                otherwise the bill joins the connector's history in altdata.evaluate
A lease that ends before the loan would be repaid is raised as a signal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.altdata import KIND_TH, EBill
from app.models import AltDataRecord, Case, Transaction

AMOUNT_TOL = Decimal("1.00")
PAY_BEFORE_DUE = timedelta(days=45)
PAY_AFTER_DUE = timedelta(days=120)
PAID_DATE_TOL_DAYS = 3
KEYWORDS = {
    "electricity": re.compile(r"ค่าไฟฟ้า|การไฟฟ้า"),
    "water": re.compile(r"ค่าน้ำประปา|การประปา"),
    "rent": re.compile(r"ค่าเช่า"),
}


@dataclass
class BillsResult:
    bills: list[EBill]  # what altdata.evaluate should see
    counts: dict[str, int] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)


def _be(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}/{d.year + 543}"


def _label(r: AltDataRecord) -> str:
    return f"{KIND_TH.get(r.kind, r.kind)} งวด {r.period}"


def _match(r: AltDataRecord, debits: list[Transaction], used: set[int]) -> Transaction | None:
    best: tuple[int, Transaction] | None = None
    for t in debits:
        if t.id in used or abs(t.debit - r.amount) > AMOUNT_TOL:
            continue
        day = t.posted_at.date()
        if not (r.due_date - PAY_BEFORE_DUE <= day <= r.due_date + PAY_AFTER_DUE):
            continue
        text = f"{t.description} {t.counterparty_name or ''}"
        if not ((r.customer_no and r.customer_no in text) or KEYWORDS[r.kind].search(text)
                or (r.provider and r.provider in text)):
            continue
        gap = abs((day - r.due_date).days)
        if best is None or gap < best[0]:
            best = (gap, t)
    return best[1] if best else None


def reconcile(db: Session, case: Case, rows: list[Transaction], as_of: date) -> BillsResult:
    records = list(db.scalars(select(AltDataRecord).where(AltDataRecord.case_id == case.id)
                              .order_by(AltDataRecord.period, AltDataRecord.id)))
    connector = [r for r in records if r.source != "bill_upload"]
    uploads = [r for r in records if r.source == "bill_upload"]
    on_feed = {(r.kind, r.period): r for r in connector}
    debits = sorted((t for t in rows if t.debit > 0), key=lambda t: (t.posted_at, t.id))
    used_txns: set[int] = set()

    out = BillsResult([EBill(r.kind, r.period, r.due_date, r.paid_date, r.amount) for r in connector])
    counts = dict.fromkeys(("uploaded", "used", "corroborated", "conflict", "payment_not_found", "held_review"), 0)
    counts["uploaded"] = len(uploads)
    for r in uploads:
        r.matched_transaction_id, r.status_note = None, None
        if r.review_status == "pending":
            r.status = "held_review"
            r.status_note = "OCR อ่านไม่มั่นใจ — รอเจ้าหน้าที่ตรวจทาน"
            counts["held_review"] += 1
            continue
        paid_txn = _match(r, debits, used_txns)
        if paid_txn:
            used_txns.add(paid_txn.id)
            r.matched_transaction_id = paid_txn.id
        paid = r.paid_date or (paid_txn.posted_at.date() if paid_txn else None)

        feed = on_feed.get((r.kind, r.period))
        if feed is not None:
            differences = []
            if abs(feed.amount - r.amount) > AMOUNT_TOL:
                differences.append(f"ยอด {r.amount:,.2f} vs {feed.amount:,.2f}")
            if paid and feed.paid_date and abs((feed.paid_date - paid).days) > PAID_DATE_TOL_DAYS:
                differences.append(f"วันชำระ {_be(paid)} vs {_be(feed.paid_date)}")
            if differences:
                r.status = "conflict"
                r.status_note = "ไม่ตรงกับข้อมูลจากผู้ให้บริการ (" + ", ".join(differences) + ") — ใช้ข้อมูลผู้ให้บริการ"
                out.signals.append(f"{_label(r)}: บิลที่อัปโหลด{r.status_note}")
            else:
                r.status = "corroborated"
                r.status_note = "ตรงกับข้อมูลจากผู้ให้บริการ"
            counts[r.status] += 1
            continue
        if paid is None and r.due_date < as_of:
            r.status = "payment_not_found"
            r.status_note = "ไม่พบใบเสร็จหรือรายการชำระในสเตทเมนต์ — ไม่นับเป็นค้างชำระ ควรสอบถามผู้กู้"
            out.signals.append(f"{_label(r)}: {r.status_note}")
            counts["payment_not_found"] += 1
            continue
        r.status = "used"
        if paid and paid > r.due_date:
            r.status_note = f"ชำระหลังกำหนด {(paid - r.due_date).days} วัน"
        elif paid:
            r.status_note = "ชำระตรงเวลา" + (" (ตามรายการในสเตทเมนต์)" if r.paid_date is None else " (ตามใบเสร็จ)")
        else:
            r.status_note = "ยังไม่ถึงกำหนดชำระ"
        counts["used"] += 1
        out.bills.append(EBill(r.kind, r.period, r.due_date, paid, r.amount))

    maturity = _add_months(as_of, case.tenor_months)
    for r in records:
        if r.lease_end and r.lease_end < maturity:
            out.signals.append(f"สัญญาเช่าสถานประกอบการสิ้นสุด {_be(r.lease_end)} ก่อนสินเชื่อครบกำหนด ({_be(maturity)}) "
                               "— ควรขอสัญญาต่ออายุหรือจำกัดอายุสินเชื่อ")
            break
    out.counts = counts
    return out


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError(d)
