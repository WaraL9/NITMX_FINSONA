from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Case, Document, Page, Transaction
from app.schemas import ApiError, DocumentKind, DocumentOut, TransactionOut, TransactionPage
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
    file: UploadFile = File(...),
    kind: DocumentKind = Form("statement"),
    password: str | None = Form(None),
    account_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    _require_case(db, case_id)
    data = await file.read()
    try:
        result = ingest_document(
            db, case_id, data, file.filename or "upload.pdf", kind=kind, password=password or None,
            account_id=account_id,
        )
    except IngestError as e:
        db.rollback()
        return JSONResponse(status_code=e.status, content={"code": e.code, "message": e.message, **e.extra})
    return result.document


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
    if q:
        like = f"%{q}%"
        filters.append(Transaction.description.like(like) | Transaction.counterparty_name.like(like))
    total = db.scalar(select(func.count()).select_from(Transaction).where(*filters)) or 0
    rows = db.execute(
        select(Transaction, Page.page_no)
        .outerjoin(Page, Page.id == Transaction.page_id)
        .where(*filters)
        .order_by(Transaction.posted_at, Transaction.account_id, Transaction.row_index)
        .offset(offset)
        .limit(limit)
    ).all()
    items = [
        TransactionOut(
            id=t.id,
            account_id=t.account_id,
            document_id=t.document_id,
            page_no=page_no,
            row_index=t.row_index,
            posted_at=t.posted_at,
            code=t.code,
            channel=t.channel,
            description=t.description,
            debit=t.debit,
            credit=t.credit,
            balance=t.balance,
            counterparty_name=t.counterparty_name,
            counterparty_bank=t.counterparty_bank,
            counterparty_account=t.counterparty_account,
            bbox=[t.bbox_x0, t.bbox_y0, t.bbox_x1, t.bbox_y1] if t.bbox_x0 is not None else None,
            confidence=t.confidence,
            extractor_version=t.extractor_version,
        )
        for t, page_no in rows
    ]
    return TransactionPage(total=total, offset=offset, limit=limit, items=items)
