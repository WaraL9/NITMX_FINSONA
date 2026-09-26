from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, current_user
from app.db import get_db
from app.services import audit
from app.api.metrics import metric_filters
from app.models import Account, Case, Document, Page, Transaction, User
from app.api.common import txn_out
from app.schemas import ApiError, DocumentKind, DocumentOut, TransactionPage
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
    user: User = Depends(current_user),
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


@router.get("/api/cases/{case_id}/documents", response_model=list[DocumentOut])
def list_documents(case_id: int, db: Session = Depends(get_db)):
    _require_case(db, case_id)
    return list(db.scalars(select(Document).where(Document.case_id == case_id).order_by(Document.uploaded_at)))


@router.get("/api/documents/{document_id}/file", response_class=FileResponse)
def document_file(document_id: int, db: Session = Depends(get_db)):
    """The document for viewing: the decrypted copy if the original was password-protected."""
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    path = Path(doc.view_path or doc.storage_path)
    if not path.exists():
        raise HTTPException(410, "file missing from storage")
    return FileResponse(path, media_type=doc.mime, filename=doc.filename, content_disposition_type="inline")


@router.get("/api/cases/{case_id}/transactions", response_model=TransactionPage)
def list_transactions(
    case_id: int,
    account_id: int | None = None,
    document_id: int | None = None,
    q: str | None = Query(None, max_length=100, description="search description / counterparty"),
    tier: str | None = None,
    tag: str | None = None,
    loop_id: str | None = None,
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
