"""Document ingestion (E2-01, E2-03, E2-15).

upload bytes -> SHA-256 -> store original -> decrypt if needed -> parse -> match account
-> persist Document, Pages and Transactions (with bounding boxes).

The PDF password is used in memory only and never stored. When the original is
encrypted, a decrypted copy is kept for the lineage viewer; the SHA-256 always refers to
the original bytes exactly as uploaded.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.config import settings
from app.core.money import to_money
import pdfplumber

from app.models import Account, AltDataRecord, Case, Document, Invoice, Page, TaxFiling, Transaction
from app.ocr.base import OcrResult, OcrUnavailable
from app.ocr.images import BadImage, image_to_pdf, sniff_image
from app.ocr.base import get_provider as get_ocr_provider
from app.services import ocr_review
from app.parsers.base import (NoTextLayer, ParsedRow, ParsedStatement, ParseError, UnsupportedFormat,
                               parse_statement, parse_statement_words)
from app.parsers.etax import (ParsedETax, detect_etax_pdf, embedded_xml, looks_like_xml, parse_etax_pdf,
                              parse_etax_xml)
from app.parsers.bill import ParsedBill, detect_bill, page_text, parse_bill_words, text_layer_words
from app.parsers.pp30 import ParsedPP30, detect_pp30, parse_pp30

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DOCUMENT_KINDS = {"auto", "statement", "pp30", "etax_invoice", "utility_bill", "evidence"}


class IngestError(Exception):
    """Base for errors the API turns into a 4xx with a machine-readable code."""

    code = "ingest_error"
    status = 422

    def __init__(self, message: str, **extra):
        super().__init__(message)
        self.message = message
        self.extra = extra


class OverlappingStatement(IngestError):
    code = "overlapping_statement"
    status = 409


class PasswordRequired(IngestError):
    code = "password_required"


class PasswordIncorrect(IngestError):
    code = "password_incorrect"


class DuplicateDocument(IngestError):
    code = "duplicate_document"
    status = 409


class NotAPdf(IngestError):
    code = "not_a_pdf"


class UnsupportedDocument(IngestError):
    code = "unsupported_format"


class ParseFailed(IngestError):
    code = "parse_failed"


class DuplicateInvoice(IngestError):
    code = "duplicate_invoice"
    status = 409


class SellerMismatch(IngestError):
    code = "seller_mismatch"


class BadRequest(IngestError):
    code = "bad_request"
    status = 400


@dataclass
class IngestResult:
    document: Document
    statement: ParsedStatement | None
    account_created: bool
    pp30: ParsedPP30 | None = None
    etax: ParsedETax | None = None
    bill: ParsedBill | None = None


def detect_kind(plain: bytes) -> str:
    """Guess the document type from page 1 (statements are the default)."""
    try:
        if embedded_xml(PdfReader(io.BytesIO(plain))):
            return "etax_invoice"  # PDF/A-3 e-Tax invoice with its XML attached
        with pdfplumber.open(io.BytesIO(plain)) as pdf:
            first = (pdf.pages[0].extract_text() or "") if pdf.pages else ""
    except Exception:
        return "statement"
    if detect_pp30(first):
        return "pp30"
    if detect_etax_pdf(first):
        return "etax_invoice"
    if detect_bill(first):
        return "utility_bill"
    return "statement" if first.strip() else "scan"  # no text layer: decide after OCR


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decrypt(data: bytes, password: str | None) -> tuple[bytes, bool]:
    """Return (plain PDF bytes, was_encrypted)."""
    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as e:
        raise NotAPdf(f"not a readable PDF: {e}") from e
    if not reader.is_encrypted:
        return data, False
    if not password:
        raise PasswordRequired("this PDF is password-protected")
    try:
        ok = reader.decrypt(password)
    except Exception as e:  # pypdf raises various errors for unsupported crypto
        raise PasswordIncorrect(f"could not decrypt: {e}") from e
    if not ok:
        raise PasswordIncorrect("wrong password")
    writer = PdfWriter(clone_from=reader)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue(), True


_LAST4 = re.compile(r"(\d{4})")


def _last4(account_no: str | None) -> str | None:
    if not account_no:
        return None
    m = _LAST4.findall(account_no)
    return m[-1] if m else None


def _match_account(db: Session, case: Case, stmt: ParsedStatement, account_id: int | None) -> tuple[Account, bool]:
    if account_id is not None:
        acct = db.get(Account, account_id)
        if acct is None or acct.case_id != case.id:
            raise BadRequest(f"account {account_id} does not belong to case {case.id}")
        return acct, False
    last4 = _last4(stmt.account_no)
    for a in case.accounts:
        if last4 and _last4(a.account_no_masked) == last4 and (not stmt.bank_code or a.bank_code == stmt.bank_code):
            return a, False
    # Unknown account: add it; ownership defaults to company and the CA can change it (E2-15).
    acct = Account(
        case_id=case.id,
        bank_code=stmt.bank_code or "UNKNOWN",
        account_no_masked=stmt.account_no or "unknown",
        account_name=stmt.account_name or "",
        account_type="unknown",
        owner_type="company",
    )
    db.add(acct)
    db.flush()
    return acct, True


def ingest_document(
    db: Session,
    case_id: int,
    data: bytes,
    filename: str,
    kind: str = "statement",
    password: str | None = None,
    account_id: int | None = None,
    user_id: int | None = None,
) -> IngestResult:
    if kind not in DOCUMENT_KINDS:
        raise BadRequest(f"unknown document kind {kind!r}")
    if not data:
        raise BadRequest("empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise BadRequest(f"file larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    case = db.get(Case, case_id)
    if case is None:
        raise BadRequest(f"case {case_id} not found")

    digest = sha256_hex(data)
    existing = db.scalar(select(Document).where(Document.case_id == case_id, Document.sha256 == digest))
    if existing:
        raise DuplicateDocument("this exact file is already in the case", existing_document_id=existing.id)

    is_xml = looks_like_xml(data)
    image_mime = sniff_image(data)
    if is_xml:
        if kind not in ("auto", "etax_invoice"):
            raise NotAPdf("XML is only accepted for e-Tax invoices")
        plain, encrypted, kind = data, False, "etax_invoice"
    elif image_mime:
        # Phone photo or image scan: an upright one-page PDF for OCR and the viewer (E2-08).
        try:
            plain, encrypted = image_to_pdf(data), False
        except BadImage as e:
            raise NotAPdf(str(e)) from e
    else:
        plain, encrypted = _decrypt(data, password)
    ocr: OcrResult | None = None
    if kind == "auto":
        kind = "scan" if image_mime else detect_kind(plain)
    if kind == "scan" or (image_mime and kind in ("statement", "utility_bill")):
        ocr = _ocr(plain, digest)
        if kind == "scan":
            kind = "utility_bill" if detect_bill(page_text(ocr.pages)) else "statement"

    stmt: ParsedStatement | None = None
    pp30: ParsedPP30 | None = None
    etax: ParsedETax | None = None
    bill: ParsedBill | None = None
    if image_mime and kind not in ("statement", "utility_bill", "evidence"):
        raise UnsupportedDocument("รูปภาพรับเฉพาะสเตทเมนต์ บิลค่าสาธารณูปโภค/ค่าเช่า และเอกสารประกอบ")
    if kind == "utility_bill":
        try:
            if ocr is None:
                words = text_layer_words(plain)
                if not any(p.words for p in words):
                    ocr = _ocr(plain, digest)
            bill = parse_bill_words(ocr.pages if ocr else words)
        except UnsupportedFormat as e:
            raise UnsupportedDocument(str(e)) from e
        except ParseError as e:
            raise ParseFailed(str(e)) from e
    if kind == "etax_invoice":
        try:
            etax = parse_etax_xml(plain) if is_xml else parse_etax_pdf(plain)
        except UnsupportedFormat as e:
            raise UnsupportedDocument(str(e)) from e
        except ParseError as e:
            raise ParseFailed(str(e)) from e
        _check_etax(db, case, etax)
    if kind == "pp30":
        try:
            pp30 = parse_pp30(io.BytesIO(plain))
        except ParseError as e:
            raise ParseFailed(str(e)) from e
    if kind == "statement":
        try:
            if ocr is not None:
                raise NoTextLayer("already OCR'd")
            stmt = parse_statement(io.BytesIO(plain))
        except NoTextLayer:
            # Scanned/photographed statement: OCR, then the same layout parser (E2-08).
            try:
                ocr = ocr or _ocr(plain, digest)
                stmt = parse_statement_words(ocr.pages)
            except UnsupportedFormat as e:
                raise UnsupportedDocument(f"OCR read the file but the layout is not recognised: {e}") from e
            except ParseError as e:
                raise ParseFailed(f"OCR: {e}") from e
        except UnsupportedFormat as e:
            raise UnsupportedDocument(str(e)) from e
        except ParseError as e:
            raise ParseFailed(str(e)) from e

    account, created = (None, False)
    duplicates_skipped = 0
    if stmt is not None:
        account, created = _match_account(db, case, stmt, account_id)
        # E2-11: an overlapping statement for the same account repeats rows already in the case.
        # Counting them twice would inflate revenue, so they are skipped (same account, time,
        # amounts and printed balance = the same bank transaction).
        existing = set(db.execute(select(Transaction.posted_at, Transaction.debit, Transaction.credit,
                                         Transaction.balance).where(Transaction.account_id == account.id)).all())
        if existing:
            fresh = [r for r in stmt.rows if (r.posted_at, r.debit, r.credit, r.balance) not in existing]
            duplicates_skipped = len(stmt.rows) - len(fresh)
            if stmt.rows and not fresh:
                raise OverlappingStatement(
                    "ธุรกรรมทุกรายการในไฟล์นี้มีอยู่ในแฟ้มแล้ว (สเตทเมนต์บัญชีเดียวกันช่วงเวลาซ้ำ)",
                    account_id=account.id)
            new_rows = fresh
        else:
            new_rows = stmt.rows

    folder: Path = settings.storage_dir / f"case_{case_id}"
    folder.mkdir(parents=True, exist_ok=True)
    ext = "xml" if is_xml else {"image/jpeg": "jpg", "image/png": "png"}.get(image_mime or "", "pdf")
    original = folder / f"{digest}.{ext}"
    storage.write(original, data)
    view = None
    if encrypted or image_mime:
        view = folder / f"{digest}.view.pdf"
        storage.write(view, plain)

    doc = Document(
        case_id=case_id,
        account_id=account.id if account else account_id,
        kind=kind,
        filename=Path(filename).name[:255] or f"upload.{ext}",
        sha256=digest,
        storage_path=str(original),
        view_path=str(view) if view else None,
        mime="application/xml" if is_xml else (image_mime or "application/pdf"),
        page_count=0 if is_xml else len(PdfReader(io.BytesIO(plain)).pages),
        uploaded_by=user_id,
    )
    db.add(doc)
    db.flush()

    if stmt is not None:
        page_ids: dict[int, int] = {}
        for p in stmt.pages:
            page = Page(document_id=doc.id, page_no=p.page_no, width=p.width, height=p.height)
            db.add(page)
            db.flush()
            page_ids[p.page_no] = page.id
        add_rows(db, case_id, account.id, doc.id, new_rows, page_ids, stmt.parser_version, ocr=ocr is not None)
        doc.parser = f"ocr:{ocr.provider}+{stmt.parser}" if ocr else stmt.parser
        doc.parse_report = statement_report(stmt, encrypted=encrypted, created=created,
                                            duplicates_skipped=duplicates_skipped)
        if ocr is not None:
            doc.parse_report["ocr"] = {"provider": ocr.provider, "model": ocr.model, "words": ocr.word_count,
                                       "mean_confidence": ocr.mean_confidence,
                                       "threshold": settings.ocr_review_threshold}
            db.flush()
            ocr_review.flag_document(db, doc)
    if pp30 is not None:
        _store_pp30(db, case, doc, pp30)
    if etax is not None:
        _store_etax(db, case, doc, etax)
    if bill is not None:
        _store_bill(db, doc, bill, ocr)
    db.commit()
    db.refresh(doc)
    return IngestResult(doc, stmt, created, pp30, etax, bill)


def statement_report(stmt: ParsedStatement, *, encrypted: bool, created: bool, duplicates_skipped: int = 0) -> dict:
    breaks = stmt.continuity_breaks()
    return {
        "parser": stmt.parser,
        "parser_version": stmt.parser_version,
        "rows": len(stmt.rows),
        "pages": len(stmt.pages),
        "bank_code": stmt.bank_code,
        "account_no": stmt.account_no,
        "account_name": stmt.account_name,
        "period_start": stmt.period_start.isoformat() if stmt.period_start else None,
        "period_end": stmt.period_end.isoformat() if stmt.period_end else None,
        "opening_balance": f"{stmt.opening_balance:.2f}" if stmt.opening_balance is not None else None,
        "closing_balance": f"{stmt.rows[-1].balance:.2f}" if stmt.rows else None,
        "total_debit": f"{stmt.total_debit:.2f}",
        "total_credit": f"{stmt.total_credit:.2f}",
        "continuity_ok": not breaks,
        "continuity_breaks": breaks[:50],
        "was_encrypted": encrypted,
        "account_created": created,
        "warnings": stmt.warnings + (
            [f"{duplicates_skipped} รายการซ้ำกับสเตทเมนต์ที่อัปโหลดแล้ว — ไม่นับซ้ำ"] if duplicates_skipped else []),
        "duplicate_rows_skipped": duplicates_skipped,
        "duplicate_pages": stmt.duplicate_pages,
    }


def add_rows(db: Session, case_id: int, account_id: int, document_id: int, rows: list[ParsedRow],
             page_ids: dict[int, int], version: str, ocr: bool = False) -> None:
    db.add_all(
        Transaction(
            case_id=case_id,
            account_id=account_id,
            document_id=document_id,
            page_id=page_ids.get(r.page_no),
            row_index=r.row_index,
            posted_at=r.posted_at,
            description=r.description,
            code=r.code,
            channel=r.channel,
            debit=r.debit,
            credit=r.credit,
            balance=r.balance,
            counterparty_name=r.counterparty_name,
            counterparty_account=r.counterparty_account,
            counterparty_bank=r.counterparty_bank,
            bbox_x0=r.bbox.x0 if r.bbox else None,
            bbox_y0=r.bbox.top if r.bbox else None,
            bbox_x1=r.bbox.x1 if r.bbox else None,
            bbox_y1=r.bbox.bottom if r.bbox else None,
            confidence=r.confidence,
            extractor_version=version,
            ocr_fields=r.field_confidence if ocr else None,
        )
        for r in rows
    )


def _ocr(plain: bytes, digest: str) -> OcrResult:
    try:
        return get_ocr_provider().analyze(plain, digest)
    except OcrUnavailable as e:
        raise UnsupportedDocument(str(e)) from e


def _store_bill(db: Session, doc: Document, b: ParsedBill, ocr: OcrResult | None) -> None:
    db.add(Page(document_id=doc.id, page_no=1, width=b.page_width, height=b.page_height))
    low = sorted(f for f, c in b.confidence.items() if c < settings.ocr_review_threshold)
    db.add(AltDataRecord(
        case_id=doc.case_id, kind=b.kind, period=b.period, due_date=b.due_date, paid_date=b.paid_date,
        amount=b.amount, source="bill_upload", document_id=doc.id, provider=b.provider,
        customer_no=b.customer_no, lease_end=b.lease_end, review_status="pending" if low else None,
        field_confidence=b.confidence or None,
    ))
    doc.parser = f"ocr:{ocr.provider}+{b.parser}" if ocr else b.parser
    doc.parse_report = {
        "parser": b.parser,
        "parser_version": b.parser_version,
        "bill_kind": b.kind,
        "is_receipt": b.is_receipt,
        "provider": b.provider,
        "customer_name": b.customer_name,
        "customer_no": b.customer_no,
        "period": b.period,
        "due_date": b.due_date.isoformat(),
        "paid_date": b.paid_date.isoformat() if b.paid_date else None,
        "lease_end": b.lease_end.isoformat() if b.lease_end else None,
        "amount": f"{b.amount:.2f}",
        "bboxes": {k: [v.x0, v.top, v.x1, v.bottom] for k, v in b.bboxes.items()},
        "field_confidence": b.confidence,
        "low_confidence": low,
        "ocr": {"provider": ocr.provider, "mean_confidence": ocr.mean_confidence} if ocr else None,
        "warnings": b.warnings + ([f"OCR อ่าน {', '.join(low)} ไม่มั่นใจ — รอเจ้าหน้าที่ตรวจทานก่อนนำมาใช้"] if low else []),
    }


def _check_etax(db: Session, case: Case, inv: ParsedETax) -> None:
    """An invoice proves this applicant's revenue only if the applicant issued it, once."""
    if case.tax_id and inv.seller_tax_id != case.tax_id:
        raise SellerMismatch(
            f"ใบกำกับภาษีนี้ออกโดยผู้ขายเลขประจำตัวผู้เสียภาษี {inv.seller_tax_id or 'ไม่ระบุ'} "
            f"ไม่ใช่ผู้ขอสินเชื่อ ({case.tax_id}) — ใช้ยืนยันรายได้ของกิจการนี้ไม่ได้",
            seller_tax_id=inv.seller_tax_id)
    existing = db.scalar(select(Invoice).where(Invoice.case_id == case.id, Invoice.source == "etax_upload",
                                               Invoice.invoice_no == inv.invoice_no))
    if existing:
        raise DuplicateInvoice(f"ใบกำกับภาษีเลขที่ {inv.invoice_no} อยู่ในแฟ้มแล้ว (ไฟล์ XML/PDF ของใบเดียวกัน)",
                               existing_document_id=existing.document_id)


def _store_etax(db: Session, case: Case, doc: Document, inv: ParsedETax) -> None:
    if inv.page_width is not None:
        db.add(Page(document_id=doc.id, page_no=1, width=inv.page_width, height=inv.page_height))
    warnings = list(inv.warnings)
    if not case.tax_id:
        warnings.append("แฟ้มยังไม่มีเลขประจำตัวผู้เสียภาษี — ยังยืนยันไม่ได้ว่าผู้ขอสินเชื่อเป็นผู้ออกใบกำกับ")
    db.add(Invoice(
        case_id=case.id, source="etax_upload", document_id=doc.id, invoice_no=inv.invoice_no,
        issue_date=inv.issue_date, seller_tax_id=inv.seller_tax_id, buyer_name=inv.buyer_name,
        buyer_tax_id=inv.buyer_tax_id, subtotal=inv.subtotal, vat=inv.vat, amount=inv.total,
    ))
    doc.parser = inv.parser
    doc.parse_report = {
        "parser": inv.parser,
        "parser_version": inv.parser_version,
        "source": inv.source,
        "invoice_no": inv.invoice_no,
        "type_code": inv.type_code,
        "type_name": inv.type_name,
        "issue_date": inv.issue_date.isoformat(),
        "seller_name": inv.seller_name,
        "seller_tax_id": inv.seller_tax_id,
        "buyer_name": inv.buyer_name,
        "buyer_tax_id": inv.buyer_tax_id,
        "currency": inv.currency,
        "amounts": {"subtotal": f"{inv.subtotal:.2f}", "vat": f"{inv.vat:.2f}", "total": f"{inv.total:.2f}"},
        "bboxes": {k: [b.x0, b.top, b.x1, b.bottom] for k, b in inv.bboxes.items()},
        "signature": inv.signature,
        "warnings": warnings,
    }


def _store_pp30(db: Session, case: Case, doc: Document, f: ParsedPP30) -> None:
    db.add(Page(document_id=doc.id, page_no=1, width=f.page_width, height=f.page_height))
    warnings = list(f.warnings)
    if case.tax_id and f.tax_id != case.tax_id:
        warnings.append(f"tax ID {f.tax_id} does not match the case ({case.tax_id})")
    # A later filing for the same month (e.g. an amended return) replaces the earlier one.
    existing = db.scalar(select(TaxFiling).where(TaxFiling.case_id == case.id, TaxFiling.period == f.period))
    if existing:
        db.delete(existing)
        warnings.append(f"replaced earlier ภ.พ.30 for {f.period}")
    zero = to_money(0)
    db.add(TaxFiling(
        case_id=case.id,
        period=f.period,
        sales=f.amounts["sales"],
        purchases=f.amounts.get("purchases", zero),
        vat_payable=f.amounts.get("vat_payable", zero),
        output_vat=f.amounts.get("output_vat", zero),
        document_id=doc.id,
    ))
    doc.parser = f.parser
    doc.parse_report = {
        "parser": f.parser,
        "parser_version": f.parser_version,
        "tax_id": f.tax_id,
        "period": f.period,
        "amounts": {k: f"{v:.2f}" for k, v in f.amounts.items()},
        "bboxes": {k: [b.x0, b.top, b.x1, b.bottom] for k, b in f.bboxes.items()},
        "warnings": warnings,
    }
