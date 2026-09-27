"""e-Tax invoice parser (E2-13).

Two inputs, one result:
  * XML following the ETDA standard (ขมธอ. 3-2560, UN/CEFACT Cross Industry Invoice
    profile): the authoritative format the Revenue Department receives.
  * PDF: first look for the XML the standard embeds in a PDF/A-3 e-Tax invoice; only when
    there is none, read the printed labels from the text layer (weakest evidence).

The result carries invoice no, issue date, seller, buyer and amounts. Amounts are
Decimal; the parser never computes a total, it only checks the printed ones agree.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pdfplumber
from pypdf import PdfReader

from app.core.dates import parse_thai_date
from app.core.money import MoneyError, to_money
from app.parsers.base import BBox, NoTextLayer, ParseError, UnsupportedFormat

PARSER_VERSION = "etax-v1.0"
DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
VAT_RATE = Decimal("0.07")
TOLERANCE = Decimal("0.01")

# ETDA document type codes that are tax invoices for a sale.
TAX_INVOICE_TYPES = {
    "388": "ใบกำกับภาษี",
    "T02": "ใบแจ้งหนี้/ใบกำกับภาษี",
    "T03": "ใบเสร็จรับเงิน/ใบกำกับภาษี",
    "T04": "ใบส่งของ/ใบกำกับภาษี",
}
NOT_A_SALE_TYPES = {
    "80": "ใบเพิ่มหนี้",
    "81": "ใบลดหนี้",
    "T01": "ใบรับ (ใบเสร็จรับเงิน)",
    "T05": "ใบกำกับภาษีอย่างย่อ",
}


@dataclass
class ParsedETax:
    parser: str
    parser_version: str
    source: str  # xml | pdf_embedded_xml | pdf_text
    invoice_no: str
    type_code: str
    issue_date: date
    seller_name: str
    seller_tax_id: str | None
    buyer_name: str
    buyer_tax_id: str | None
    subtotal: Decimal  # excl. VAT
    vat: Decimal
    total: Decimal  # incl. VAT
    currency: str = "THB"
    signature: str = "absent"  # present_unverified | absent
    page_width: float | None = None
    page_height: float | None = None
    bboxes: dict[str, BBox] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def type_name(self) -> str:
        return TAX_INVOICE_TYPES.get(self.type_code, self.type_code)


def looks_like_xml(data: bytes) -> bool:
    head = data[:64].lstrip(b"\xef\xbb\xbf \t\r\n")
    return head.startswith(b"<")


def _tax_id(raw: str | None) -> str | None:
    """ETDA TXID = 13-digit tax ID + 5-digit branch; keep the tax ID."""
    digits = re.sub(r"\D", "", raw or "")
    return digits[:13] if len(digits) >= 13 else None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: ET.Element | None, *path: str) -> ET.Element | None:
    """Follow a path of local names, ignoring namespaces (ETDA schema versions differ)."""
    for name in path:
        if el is None:
            return None
        el = next((c for c in el if _local(c.tag) == name), None)
    return el


def _text(el: ET.Element | None, *path: str) -> str | None:
    found = _child(el, *path)
    return found.text.strip() if found is not None and found.text and found.text.strip() else None


def _amount(settlement: ET.Element | None, name: str) -> Decimal | None:
    raw = _text(settlement, "SpecifiedTradeSettlementHeaderMonetarySummation", name)
    if raw is None:
        return None
    try:
        return to_money(raw)
    except MoneyError as e:
        raise ParseError(f"{name} is not an amount: {raw!r}") from e


def _check_totals(subtotal: Decimal, vat: Decimal, total: Decimal) -> list[str]:
    warnings = []
    if abs(subtotal + vat - total) > TOLERANCE:
        warnings.append("ยอดรวมทั้งสิ้นไม่เท่ากับมูลค่าสินค้า + ภาษีมูลค่าเพิ่ม")
    if abs((subtotal * VAT_RATE).quantize(TOLERANCE) - vat) > TOLERANCE:
        warnings.append("ภาษีมูลค่าเพิ่มไม่เท่ากับ 7% ของมูลค่าสินค้า")
    if total <= 0:
        warnings.append("ยอดรวมไม่เป็นบวก")
    return warnings


def parse_etax_xml(data: bytes, source: str = "xml") -> ParsedETax:
    # Invoices come from outside the bank: refuse DTDs outright (no entity expansion, no XXE).
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ParseError("XML with a DTD/entities is not accepted")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise UnsupportedFormat(f"not well-formed XML: {e}") from e
    if not _local(root.tag).endswith("CrossIndustryInvoice"):
        raise UnsupportedFormat(f"not an ETDA e-Tax invoice (root element {_local(root.tag)})")

    doc = _child(root, "ExchangedDocument")
    invoice_no = _text(doc, "ID")
    type_code = _text(doc, "TypeCode") or ""
    issued = _text(doc, "IssueDateTime")
    if type_code in NOT_A_SALE_TYPES:
        raise UnsupportedFormat(f"{NOT_A_SALE_TYPES[type_code]} ({type_code}) ไม่ใช่ใบกำกับภาษีขาย — ใช้ยืนยันรายได้ไม่ได้")
    if type_code not in TAX_INVOICE_TYPES:
        raise UnsupportedFormat(f"unknown e-Tax document type {type_code!r}")
    if not invoice_no or not issued:
        raise ParseError("e-Tax invoice is missing its number or issue date")
    try:
        issue_date = date.fromisoformat(issued[:10])
    except ValueError as e:
        raise ParseError(f"bad IssueDateTime {issued!r}") from e

    trade = _child(root, "SupplyChainTradeTransaction")
    agreement = _child(trade, "ApplicableHeaderTradeAgreement")
    seller = _child(agreement, "SellerTradeParty")
    buyer = _child(agreement, "BuyerTradeParty")
    settlement = _child(trade, "ApplicableHeaderTradeSettlement")
    seller_name, buyer_name = _text(seller, "Name"), _text(buyer, "Name")
    if not seller_name or not buyer_name:
        raise ParseError("e-Tax invoice is missing the seller or buyer name")

    subtotal = _amount(settlement, "TaxBasisTotalAmount")
    vat = _amount(settlement, "TaxTotalAmount")
    total = _amount(settlement, "GrandTotalAmount")
    if subtotal is None or vat is None or total is None:
        raise ParseError("e-Tax invoice is missing TaxBasisTotalAmount, TaxTotalAmount or GrandTotalAmount")
    currency = _text(settlement, "InvoiceCurrencyCode") or "THB"

    warnings = _check_totals(subtotal, vat, total)
    if currency != "THB":
        warnings.append(f"สกุลเงิน {currency} — จับคู่กับรายการรับเงินบาทไม่ได้")
    signed = root.find(f".//{{{DSIG_NS}}}Signature") is not None
    if not signed:
        warnings.append("ไม่มีลายมือชื่อดิจิทัล — เป็นหลักฐานที่ผู้กู้จัดทำเอง")
    seller_tax = _tax_id(_text(seller, "SpecifiedTaxRegistration", "ID"))
    buyer_tax = _tax_id(_text(buyer, "SpecifiedTaxRegistration", "ID"))
    if seller_tax and seller_tax == buyer_tax:
        warnings.append("ผู้ซื้อและผู้ขายเป็นนิติบุคคลเดียวกัน")
    return ParsedETax(
        parser="etda-etax-xml", parser_version=PARSER_VERSION, source=source, invoice_no=invoice_no,
        type_code=type_code, issue_date=issue_date, seller_name=seller_name, seller_tax_id=seller_tax,
        buyer_name=buyer_name, buyer_tax_id=buyer_tax, subtotal=subtotal, vat=vat, total=total,
        currency=currency, signature="present_unverified" if signed else "absent", warnings=warnings,
    )


# ---- PDF ------------------------------------------------------------------------------------

TITLE_RE = re.compile(r"ใบกำกับภาษี|Tax\s*Invoice", re.I)
NO_RE = re.compile(r"(?:เลขที่|No\.)[^:]*:\s*(\S+)")
DATE_RE = re.compile(r"(?:วันที่|Date)[^:]*:\s*(\d{1,2}/\d{1,2}/\d{4})")
PARTY_RE = re.compile(r"^(ผู้ขาย|ผู้ซื้อ)[^:]*:\s*(.+)$")
TAXID_RE = re.compile(r"เลขประจำตัวผู้เสียภาษี(?:อากร)?\s*:?\s*([\d\- ]{13,})")
MONEY_RE = re.compile(r"^-?\d{1,3}(,\d{3})*\.\d{2}$")
TOTAL_LABELS = {"subtotal": ("รวมเป็นเงิน", "มูลค่าสินค้า"), "vat": ("ภาษีมูลค่าเพิ่ม",),
                "total": ("จำนวนเงินรวมทั้งสิ้น", "รวมทั้งสิ้น")}


def detect_etax_pdf(first_page_text: str) -> bool:
    return bool(TITLE_RE.search(first_page_text)) and "เลขประจำตัวผู้เสียภาษี" in first_page_text


def embedded_xml(reader: PdfReader) -> list[bytes]:
    """XML files attached to the PDF (PDF/A-3 e-Tax invoices carry their ETDA XML this way)."""
    try:
        attachments = reader.attachments
    except Exception:
        return []
    return [blob for name, blobs in attachments.items() if name.lower().endswith(".xml") for blob in blobs]


def parse_etax_pdf(plain: bytes) -> ParsedETax:
    reader = PdfReader(io.BytesIO(plain))
    first_error: ParseError | None = None
    for blob in embedded_xml(reader):
        try:
            parsed = parse_etax_xml(blob, source="pdf_embedded_xml")
        except UnsupportedFormat as e:
            first_error = first_error or e
            continue
        with pdfplumber.open(io.BytesIO(plain)) as pdf:
            page = pdf.pages[0]
            parsed.page_width, parsed.page_height = float(page.width), float(page.height)
            parsed.bboxes = _total_bboxes(page)[1]
        return parsed
    if first_error is not None:
        raise first_error
    return _parse_text_layer(plain)


def _lines(page) -> list[list[dict]]:
    lines: list[list[dict]] = []
    # Upright body text only: drops rotated or oversized watermarks ("COPY", "SYNTHETIC").
    words = [w for w in page.extract_words(x_tolerance=1.5, extra_attrs=["size", "upright"])
             if w["upright"] and w["size"] <= 20]
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= 2:
            lines[-1].append(w)
        else:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w["x0"])
    return lines


def _total_bboxes(page) -> tuple[dict[str, Decimal], dict[str, BBox]]:
    amounts: dict[str, Decimal] = {}
    boxes: dict[str, BBox] = {}
    for line in _lines(page):
        text = " ".join(w["text"] for w in line)
        money = [w for w in line if MONEY_RE.match(w["text"])]
        if not money:
            continue
        for key, labels in TOTAL_LABELS.items():
            if key not in amounts and any(text.startswith(label) for label in labels):
                v = money[-1]
                amounts[key] = to_money(v["text"])
                boxes[key] = BBox(line[0]["x0"] - 2, min(w["top"] for w in line) - 2, v["x1"] + 2,
                                  max(w["bottom"] for w in line) + 2)
    return amounts, boxes


def _parse_text_layer(plain: bytes) -> ParsedETax:
    with pdfplumber.open(io.BytesIO(plain)) as pdf:
        if not pdf.pages:
            raise ParseError("empty PDF")
        page = pdf.pages[0]
        text = page.extract_text() or ""
        if not text.strip():
            raise NoTextLayer("scanned invoice — no text layer and no embedded e-Tax XML")
        if not detect_etax_pdf(text):
            raise UnsupportedFormat("not a recognised tax invoice layout")
        lines = [" ".join(w["text"] for w in line) for line in _lines(page)]
        amounts, boxes = _total_bboxes(page)
        width, height = float(page.width), float(page.height)

    joined = "\n".join(lines)
    no, issued = NO_RE.search(joined), DATE_RE.search(joined)
    if not no or not issued:
        raise ParseError("tax invoice number or date not found on the PDF")
    parties: dict[str, dict[str, str | None]] = {}
    current: str | None = None
    for line in lines:
        m = PARTY_RE.match(line)
        if m:
            current = "seller" if m.group(1) == "ผู้ขาย" else "buyer"
            parties[current] = {"name": m.group(2).strip(), "tax_id": None}
            continue
        t = TAXID_RE.search(line)
        if t and current and parties[current]["tax_id"] is None:
            parties[current]["tax_id"] = _tax_id(t.group(1))
    if "seller" not in parties or "buyer" not in parties:
        raise ParseError("seller or buyer not found on the PDF")
    missing = [k for k in TOTAL_LABELS if k not in amounts]
    if missing:
        raise ParseError(f"amount line(s) not found: {', '.join(missing)}")
    try:
        issue_date = parse_thai_date(issued.group(1))
    except ValueError as e:
        raise ParseError(f"bad invoice date {issued.group(1)!r}") from e

    warnings = _check_totals(amounts["subtotal"], amounts["vat"], amounts["total"])
    warnings.append("อ่านจากข้อความบน PDF (ไม่มีไฟล์ XML ของ e-Tax แนบ) — หลักฐานอ่อนกว่า XML")
    return ParsedETax(
        parser="etax-pdf-text", parser_version=PARSER_VERSION, source="pdf_text", invoice_no=no.group(1),
        type_code="388", issue_date=issue_date, seller_name=parties["seller"]["name"] or "",
        seller_tax_id=parties["seller"]["tax_id"], buyer_name=parties["buyer"]["name"] or "",
        buyer_tax_id=parties["buyer"]["tax_id"], subtotal=amounts["subtotal"], vat=amounts["vat"],
        total=amounts["total"], page_width=width, page_height=height, bboxes=boxes, warnings=warnings,
    )
