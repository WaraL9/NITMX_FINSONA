from app.models import Transaction
from app.schemas import TransactionOut


def txn_out(t: Transaction, page_no: int | None) -> TransactionOut:
    return TransactionOut(
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
        tag=t.tag,
        tier=t.tier,
        loop_id=t.loop_id,
        tag_reason=t.tag_reason,
    )
