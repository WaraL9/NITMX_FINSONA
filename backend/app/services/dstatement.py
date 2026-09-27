"""Pull a statement from the account holder's bank through dStatement (E3-04).

Rows are split by what the case already has for that account:
  * dates no uploaded statement covers   -> imported (same rows a PDF of it would give)
  * dates an uploaded statement covers   -> verified against the bank's record instead:
        matched      same time, amounts and balance
        differs      same time, different amount/balance (an edited PDF — or an OCR misread)
        case_only    in the uploaded statement but not at the bank (added or altered)
        bank_only    at the bank but missing from the uploaded statement (hidden)
Verification never changes a figure; mismatches become a high-severity anomaly with the
rows attached, and the CA decides (override/exclude) with a reason as usual.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.config import settings
from app.connectors.base import ConnectorError, ConsentMissing
from app.connectors.dstatement import AccountNotFound, get_statement_source, verify
from app.models import Case, Document, Transaction
from app.parsers.base import ParsedRow, ParseError
from app.parsers.dstatement import parse_dstatement
from app.services import consent
from app.services.ingest import (BadRequest, DuplicateDocument, IngestError, ParseFailed, _match_account, add_rows,
                                 sha256_hex, statement_report)

MAX_LISTED = 50


class ConsentRequired(IngestError):
    code = "consent_required"
    status = 403


class AccountNotAtBank(IngestError):
    code = "account_not_found"
    status = 404


class ConnectorFailed(IngestError):
    code = "connector_error"
    status = 502


@dataclass
class PullResult:
    document: Document
    imported: int
    verification: dict | None


def _key(posted_at, debit, credit, balance) -> tuple:
    return (posted_at.replace(second=0, microsecond=0), debit, credit, balance)


def compare(existing: list[Transaction], bank: list[ParsedRow]) -> dict:
    """Multiset match on (time, debit, credit, balance), then pair leftovers by time."""
    pool: dict[tuple, list[Transaction]] = defaultdict(list)
    for t in sorted(existing, key=lambda t: (t.posted_at, t.row_index, t.id)):
        pool[_key(t.posted_at, t.debit, t.credit, t.balance)].append(t)
    matched, bank_left = 0, []
    for r in bank:
        hits = pool.get(_key(r.posted_at, r.debit, r.credit, r.balance))
        if hits:
            hits.pop(0)
            matched += 1
        else:
            bank_left.append(r)
    case_left = sorted((t for ts in pool.values() for t in ts), key=lambda t: (t.posted_at, t.id))

    by_time: dict = defaultdict(list)
    for t in case_left:
        by_time[t.posted_at.replace(second=0, microsecond=0)].append(t)
    differs, bank_only = [], []
    for r in bank_left:
        same_time = by_time.get(r.posted_at)
        if same_time:
            t = same_time.pop(0)
            fields = {f: [f"{getattr(t, f):.2f}", f"{getattr(r, f):.2f}"]
                      for f in ("debit", "credit", "balance") if getattr(t, f) != getattr(r, f)}
            differs.append({"transaction_id": t.id, "posted_at": r.posted_at.isoformat(), "fields": fields})
        else:
            bank_only.append({"posted_at": r.posted_at.isoformat(), "description": r.description,
                              "debit": f"{r.debit:.2f}", "credit": f"{r.credit:.2f}", "balance": f"{r.balance:.2f}"})
    case_only = [t.id for ts in by_time.values() for t in ts]
    return {"compared": len(bank), "matched": matched, "differs": differs[:MAX_LISTED],
            "differs_count": len(differs), "case_only": case_only[:MAX_LISTED], "case_only_count": len(case_only),
            "bank_only": bank_only[:MAX_LISTED], "bank_only_count": len(bank_only)}


def pull(db: Session, case_id: int, bank_code: str, account_no: str, start: date | None = None,
         end: date | None = None, user_id: int | None = None) -> PullResult:
    case = db.get(Case, case_id)
    if case is None:
        raise BadRequest(f"case {case_id} not found")
    grant = consent.has(db, case.id, "dstatement_data")
    if grant is None:
        raise ConsentRequired("ยังไม่ได้รับความยินยอมให้ดึงรายการเดินบัญชีผ่าน dStatement")
    if not case.tax_id:
        raise BadRequest("แฟ้มยังไม่มีเลขประจำตัวผู้เสียภาษี — ธนาคารต้นทางใช้ระบุตัวผู้ประกอบการ")
    source = get_statement_source()
    try:
        signed = source.fetch_statement(case.tax_id, bank_code, account_no, start or case.period_start,
                                        end or case.period_end, consent_token=f"consent-{grant.id}")
    except AccountNotFound as e:
        raise AccountNotAtBank(str(e)) from e
    except ConsentMissing as e:
        raise ConsentRequired(str(e)) from e
    except ConnectorError as e:
        raise ConnectorFailed(str(e)) from e
    if not verify(signed):
        raise ParseFailed("ลายมือชื่อของธนาคารต้นทางไม่ถูกต้อง — ข้อมูลอาจถูกแก้ไขระหว่างทาง")
    try:
        stmt = parse_dstatement(signed.statement)
    except ParseError as e:
        raise ParseFailed(str(e)) from e

    data = signed.to_bytes()
    digest = sha256_hex(data)
    existing_doc = db.scalar(select(Document).where(Document.case_id == case.id, Document.sha256 == digest))
    if existing_doc:
        raise DuplicateDocument("ดึงรายการชุดนี้จากธนาคารไปแล้ว (ข้อมูลตรงกันทุกไบต์)", existing_document_id=existing_doc.id)
    account, created = _match_account(db, case, stmt, None)

    # Dates already covered by an uploaded statement for this account are verified, not imported.
    covered = list(db.scalars(select(Transaction).where(Transaction.account_id == account.id)))
    span = (min(t.posted_at for t in covered), max(t.posted_at for t in covered)) if covered else None
    inside = [r for r in stmt.rows if span and span[0] <= r.posted_at <= span[1]]
    outside = [r for r in stmt.rows if not (span and span[0] <= r.posted_at <= span[1])]
    verification = None
    if inside:
        in_span = [t for t in covered if stmt.period_start <= t.posted_at.date() <= stmt.period_end]
        verification = compare(in_span, inside)

    folder: Path = settings.storage_dir / f"case_{case.id}"
    folder.mkdir(parents=True, exist_ok=True)
    original = folder / f"{digest}.json"
    storage.write(original, data)
    doc = Document(
        case_id=case.id, account_id=account.id, kind="statement",
        filename=f"dstatement_{stmt.bank_code}_{(stmt.account_no or '')[-6:].strip('-x')}_{stmt.period_start}_{stmt.period_end}.json",
        sha256=digest, storage_path=str(original), mime="application/json", page_count=0, uploaded_by=user_id,
        parser=f"{stmt.parser}:{source.mode}",
    )
    db.add(doc)
    db.flush()
    add_rows(db, case.id, account.id, doc.id, outside, {}, stmt.parser_version)
    report = statement_report(stmt, encrypted=False, created=created)
    report["source"] = {"connector": source.name, "mode": source.mode, "key_id": signed.key_id,
                        "signature_verified": True, "imported": len(outside)}
    if verification is not None:
        report["verification"] = verification
        issues = verification["differs_count"] + verification["case_only_count"] + verification["bank_only_count"]
        if issues:
            report["warnings"].append(f"สเตทเมนต์ที่อัปโหลดไม่ตรงกับข้อมูลธนาคาร {issues} จุด")
    doc.parse_report = report
    db.commit()
    db.refresh(doc)
    return PullResult(doc, len(outside), verification)
