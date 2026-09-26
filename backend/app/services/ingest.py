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

from app.models import Account, Case, Document, Page, TaxFiling, Transaction
from app.ocr.base import OcrResult, OcrUnavailable
from app.ocr.base import get_provider as get_ocr_provider
from app.services import ocr_review
from app.parsers.base import (NoTextLayer, ParsedStatement, ParseError, UnsupportedFormat, parse_statement,
                               parse_statement_words)
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


class BadRequest(IngestError):
    code = "bad_request"
    status = 400


@dataclass
class IngestResult:
    document: Document
    statement: ParsedStatement | None
    account_created: bool
    pp30: ParsedPP30 | None = None


def detect_kind(plain: bytes) -> str:
    """Guess the document type from page 1 (statements are the default)."""
    try:
        with pdfplumber.open(io.BytesIO(plain)) as pdf:
            first = (pdf.pages[0].extract_text() or "") if pdf.pages else ""
    except Exception:
        return "statement"
    return "pp30" if detect_pp30(first) else "statement"


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

    plain, encrypted = _decrypt(data, password)
    if kind == "auto":
        kind = detect_kind(plain)

    stmt: ParsedStatement | None = None
    pp30: ParsedPP30 | None = None
    ocr: OcrResult | None = None
    if kind == "pp30":
        try:
            pp30 = parse_pp30(io.BytesIO(plain))
        except ParseError as e:
            raise ParseFailed(str(e)) from e
    if kind == "statement":
        try:
            stmt = parse_statement(io.BytesIO(plain))
        except NoTextLayer:
            # Scanned/photographed statement: OCR, then the same layout parser (E2-08).
            try:
                ocr = get_ocr_provider().analyze(plain, digest)
                stmt = parse_statement_words(ocr.pages)
            except OcrUnavailable as e:
                raise UnsupportedDocument(str(e)) from e
            except UnsupportedFormat as e:
                raise UnsupportedDocument(f"OCR read the file but the layout is not recognised: {e}") from e
            except ParseError as e:
                raise ParseFailed(f"OCR: {e}") from e
        except UnsupportedFormat as e:
            raise UnsupportedDocument(str(e)) from e
        except ParseError as e:
            raise ParseFailed(str(e)) from e

    folder: Path = settings.storage_dir / f"case_{case_id}"
    folder.mkdir(parents=True, exist_ok=True)
    original = folder / f"{digest}.pdf"
    storage.write(original, data)
    view = None
    if encrypted:
        view = folder / f"{digest}.view.pdf"
        storage.write(view, plain)

    account, created = (None, False)
    if stmt is not None:
        account, created = _match_account(db, case, stmt, account_id)

    doc = Document(
        case_id=case_id,
        account_id=account.id if account else account_id,
        kind=kind,
        filename=Path(filename).name[:255] or "upload.pdf",
        sha256=digest,
        storage_path=str(original),
        view_path=str(view) if view else None,
        mime="application/pdf",
        page_count=len(PdfReader(io.BytesIO(plain)).pages),
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
        db.add_all(
            Transaction(
                case_id=case_id,
                account_id=account.id,
                document_id=doc.id,
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
                bbox_x0=r.bbox.x0,
                bbox_y0=r.bbox.top,
                bbox_x1=r.bbox.x1,
                bbox_y1=r.bbox.bottom,
                confidence=r.confidence,
                extractor_version=stmt.parser_version,
                ocr_fields=r.field_confidence if ocr else None,
            )
            for r in stmt.rows
        )
        breaks = stmt.continuity_breaks()
        doc.parser = f"ocr:{ocr.provider}+{stmt.parser}" if ocr else stmt.parser
        doc.parse_report = {
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
            "warnings": stmt.warnings,
        }
        if ocr is not None:
            doc.parse_report["ocr"] = {"provider": ocr.provider, "model": ocr.model, "words": ocr.word_count,
                                       "mean_confidence": ocr.mean_confidence,
                                       "threshold": settings.ocr_review_threshold}
            db.flush()
            ocr_review.flag_document(db, doc)
    if pp30 is not None:
        _store_pp30(db, case, doc, pp30)
    db.commit()
    db.refresh(doc)
    return IngestResult(doc, stmt, created, pp30)


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
