from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_role
from app.db import get_db
from app.services import audit, coverage
from app.api.metrics import metric_filters
from app.models import Account, AltDataRecord, Analysis, Case, Document, Invoice, Page, Transaction, User
from app import storage
from app.api.common import txn_out
from app.schemas import (ApiError, BillLinkOut, CoverageOut, DocumentKind, DocumentOut, InvoiceLinkOut,
                         TransactionPage)
from app.services.ingest import IngestError, ingest_document

router = APIRouter(tags=["documents"])

ERROR_RESPONSES = {400: {"model": ApiError}, 409: {"model": ApiError}, 422: {"model": ApiError}}


def _require_case(db: Session, case_id: int) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    return case


@router.post(
    "/api/cases/{case_id}/documents",
    response_model=DocumentOut,
    status_code=201,
    responses=ERROR_RESPONSES,
)
async def upload_document(
    case_id: int,
    request: Request,
    file: UploadFile = File(...),
    kind: DocumentKind | Literal["auto"] = Form("auto"),
    password: str | None = Form(None),
    account_id: int | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("CA", "RM", "SME")),
):
    case = _require_case(db, case_id)
    if user.role == "SME" and case.owner_user_id != user.id:
        raise HTTPException(404, "case not found")
    if user.role == "SME" and case.submitted_at is not None:
        raise HTTPException(409, "application already submitted — documents are locked")
    data = await file.read()
    try:
        result = ingest_document(
            db, case_id, data, file.filename or "upload.pdf", kind=kind, password=password or None,
            account_id=account_id, user_id=user.id,
        )
    except IngestError as e:
        db.rollback()
        return JSONResponse(status_code=e.status, content={"code": e.code, "message": e.message, **e.extra})
    doc = result.document
    audit.log(db, "document_upload", case_id=case_id, user_id=user.id, ip=client_ip(request),
              target_type="document", target_id=doc.id,
              after={"filename": doc.filename, "sha256": doc.sha256, "kind": doc.kind, "pages": doc.page_count})
    db.commit()
    return doc


@router.get("/api/cases/{case_id}/coverage", response_model=CoverageOut)
def case_coverage(case_id: int, db: Session = Depends(get_db)):
    """E2-11: which days of the case period each account's statements cover, and the gaps."""
    return coverage.compute(db, _require_case(db, case_id))


@router.get("/api/cases/{case_id}/documents", response_model=list[DocumentOut])
def list_documents(case_id: int, db: Session = Depends(get_db)):
    _require_case(db, case_id)
    docs = list(db.scalars(select(Document).where(Document.case_id == case_id).order_by(Document.uploaded_at)))
    links, bills = _invoice_links(db, case_id), _bill_links(db, case_id)
    return [DocumentOut.model_validate(d).model_copy(update={"invoice": links.get(d.id), "bill": bills.get(d.id)})
            for d in docs]


def _bill_links(db: Session, case_id: int) -> dict[int, BillLinkOut]:
    """E2-14: each uploaded bill's standing in the alt-data rules (as of the last analysis)."""
    rows = db.execute(select(AltDataRecord, Transaction, Document.uploaded_at)
                      .outerjoin(Transaction, Transaction.id == AltDataRecord.matched_transaction_id)
                      .join(Document, Document.id == AltDataRecord.document_id)
                      .where(AltDataRecord.case_id == case_id)).all()
    analysed_at = db.scalar(select(func.max(Analysis.created_at)).where(Analysis.case_id == case_id))
    out = {}
    for r, txn, uploaded_at in rows:
        fresh = analysed_at is not None and analysed_at >= uploaded_at and r.status is not None
        out[r.document_id] = BillLinkOut(
            record_id=r.id, status=r.status if fresh else "pending_analysis", note=r.status_note if fresh else None,
            review_status=r.review_status, amount=r.amount, due_date=r.due_date,
            paid_date=r.paid_date or (txn.posted_at.date() if txn else None), transaction_id=txn.id if txn else None)
    return out


def _invoice_links(db: Session, case_id: int) -> dict[int, InvoiceLinkOut]:
    """E2-13: for each uploaded e-Tax invoice, the receipt it verified (as of the last analysis)."""
    rows = db.execute(select(Invoice, Transaction, Document.uploaded_at)
                      .outerjoin(Transaction, Transaction.id == Invoice.matched_transaction_id)
                      .outerjoin(Document, Document.id == Invoice.document_id)
                      .where(Invoice.case_id == case_id)).all()
    analysed_at = db.scalar(select(func.max(Analysis.created_at)).where(Analysis.case_id == case_id))
    on_network = {i.invoice_no for i, _, _ in rows if i.source.startswith("promptbiz_")}
    out = {}
    for inv, txn, uploaded_at in rows:
        if inv.document_id is None:
            continue
        if analysed_at is None or analysed_at < uploaded_at:
            status = "pending_analysis"
        else:
            status = "duplicate_of_promptbiz" if inv.invoice_no in on_network else "matched" if txn else "unmatched"
        out[inv.document_id] = InvoiceLinkOut(
            invoice_no=inv.invoice_no, status=status, transaction_id=txn.id if txn else None,
            paid_at=txn.posted_at if txn else None, paid_amount=txn.credit if txn else None)
    return out


@router.get("/api/documents/{document_id}/file", response_class=FileResponse)
def document_file(document_id: int, original: bool = False, db: Session = Depends(get_db)):
    """The document for viewing: the decrypted copy if the original was password-protected, or
    the upright PDF made from a photo. `original=true` returns the bytes exactly as uploaded."""
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    use_view = bool(doc.view_path) and not original
    path = Path(doc.view_path if use_view else doc.storage_path)
    if not path.exists():
        raise HTTPException(410, "file missing from storage")
    if use_view:
        return storage.response(path, "application/pdf", Path(doc.filename).with_suffix(".pdf").name)
    return storage.response(path, doc.mime, doc.filename)


@router.get("/api/cases/{case_id}/transactions", response_model=TransactionPage)
def list_transactions(
    case_id: int,
    account_id: int | None = None,
    document_id: int | None = None,
    q: str | None = Query(None, max_length=100, description="search description / counterparty"),
    tier: str | None = None,
    tag: str | None = None,
    loop_id: str | None = None,
    ids: str | None = Query(None, pattern=r"^\d+(,\d+){0,499}$", description="explicit rows, e.g. the rows behind an anomaly flag"),
    metric: str | None = Query(None, description="lineage: rows behind an analysis figure, e.g. T1_golden, "
                                                 "own_account_loops, business_operating, household"),
    sort: Literal["time", "amount_desc"] = "time",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _require_case(db, case_id)
    filters = [Transaction.case_id == case_id]
    if account_id is not None:
        filters.append(Transaction.account_id == account_id)
    if document_id is not None:
        filters.append(Transaction.document_id == document_id)
    if tier:
        filters.append(Transaction.tier == tier)
    if tag:
        filters.append(Transaction.tag == tag)
    if loop_id:
        filters.append(Transaction.loop_id == loop_id)
    if ids:
        filters.append(Transaction.id.in_({int(i) for i in ids.split(",")}))
    if q:
        like = f"%{q}%"
        filters.append(Transaction.description.like(like) | Transaction.counterparty_name.like(like))
    if metric:
        try:
            filters.extend(metric_filters(metric))
        except KeyError as e:
            raise HTTPException(422, f"unknown metric {metric!r}") from e
    base = select(Transaction).join(Account, Account.id == Transaction.account_id).where(*filters).subquery()
    total, sum_debit, sum_credit = db.execute(
        select(func.count(), func.coalesce(func.sum(base.c.debit), 0), func.coalesce(func.sum(base.c.credit), 0))
    ).one()
    order = ((Transaction.credit + Transaction.debit).desc(), Transaction.posted_at) if sort == "amount_desc" else (
        Transaction.posted_at, Transaction.account_id, Transaction.row_index)
    rows = db.execute(
        select(Transaction, Page.page_no)
        .join(Account, Account.id == Transaction.account_id)
        .outerjoin(Page, Page.id == Transaction.page_id)
        .where(*filters)
        .order_by(*order)
        .offset(offset)
        .limit(limit)
    ).all()
    items = [txn_out(t, page_no) for t, page_no in rows]
    return TransactionPage(total=total or 0, offset=offset, limit=limit, items=items,
                           sum_debit=f"{Decimal(sum_debit):.2f}", sum_credit=f"{Decimal(sum_credit):.2f}")
