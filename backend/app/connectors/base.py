"""Connector interfaces (E3-01).

Every external data source sits behind an interface and declares whether it is live or a
sandbox stand-in. The UI shows that mode on every card that uses the data (E3-03), and
swapping sandbox -> live is a configuration change, not a code change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol

Mode = Literal["live", "sandbox"]


class ConnectorError(Exception):
    pass


class ConsentMissing(ConnectorError):
    pass


@dataclass
class InvoiceRecord:
    invoice_no: str
    issue_date: date
    seller_tax_id: str
    buyer_name: str
    buyer_tax_id: str | None
    subtotal: Decimal
    vat: Decimal
    total: Decimal
    wht: Decimal
    paid_amount: Decimal | None
    paid_at: datetime | None
    settlement_ref: str | None


class InvoiceSource(Protocol):
    name: str
    mode: Mode

    def fetch_invoices(self, seller_tax_id: str, consent_token: str) -> list[InvoiceRecord]: ...
