"""PromptBiz e-invoice connector (E3-02).

We have no access to NITMX's PromptBiz API, so the sandbox serves a synthetic invoice
feed with the same shape a live integration would return (e-invoice header, totals,
withholding tax, settlement status). `get_invoice_source()` picks live or sandbox from
config; only the sandbox exists today.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.connectors.base import ConnectorError, ConsentMissing, InvoiceRecord, InvoiceSource

SANDBOX_FEEDS = ("generated/*/promptbiz_invoices.json",)


def _record(d: dict) -> InvoiceRecord:
    def dec(k: str) -> Decimal | None:
        return Decimal(d[k]) if d.get(k) is not None else None

    return InvoiceRecord(
        invoice_no=d["invoice_no"],
        issue_date=date.fromisoformat(d["issue_date"]),
        seller_tax_id=d["seller_tax_id"],
        buyer_name=d["buyer_name"],
        buyer_tax_id=d.get("buyer_tax_id"),
        subtotal=dec("subtotal"),
        vat=dec("vat"),
        total=dec("total"),
        wht=dec("wht") or Decimal("0.00"),
        paid_amount=dec("paid_amount"),
        paid_at=datetime.fromisoformat(d["paid_at"]) if d.get("paid_at") else None,
        settlement_ref=d.get("settlement_ref"),
    )


@lru_cache(maxsize=8)
def _load_feed(path: Path, mtime: float) -> tuple[str, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["seller_tax_id"], data["invoices"]


def sandbox_invoices(seller_tax_id: str) -> list[dict]:
    """Raw sandbox feed for a seller (also served over HTTP by the sandbox API)."""
    for pattern in SANDBOX_FEEDS:
        for path in sorted(settings.data_dir.glob(pattern)):
            tax_id, invoices = _load_feed(path, path.stat().st_mtime)
            if tax_id == seller_tax_id:
                return invoices
    return []


class PromptBizSandbox:
    name = "PromptBiz"
    mode = "sandbox"

    def fetch_invoices(self, seller_tax_id: str, consent_token: str) -> list[InvoiceRecord]:
        if not consent_token:
            raise ConsentMissing("PromptBiz data requires the business owner's consent")
        return [_record(d) for d in sandbox_invoices(seller_tax_id)]


def get_invoice_source() -> InvoiceSource:
    if settings.connector_mode == "live":
        raise ConnectorError("live PromptBiz access is not available; set FINSONA_CONNECTOR_MODE=sandbox")
    return PromptBizSandbox()
