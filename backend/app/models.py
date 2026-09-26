"""Domain model (E0-02).

Enumerations are plain strings so SQLite stays simple; allowed values live in the
Literal types below and are enforced at the API layer.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, ExactDecimal, Money

Role = Literal["CA", "RM", "SME", "AUDITOR"]
CaseStatus = Literal["draft", "processing", "in_review", "decided"]
CaseSource = Literal["sme_portal", "rm", "branch"]
OwnerType = Literal["company", "director", "family", "external"]
DocumentKind = Literal["statement", "pp30", "etax_invoice", "utility_bill", "evidence"]
Tier = Literal["T1_golden", "T2_tax", "T3_operational", "T4_unverified"]
WatchlistStatus = Literal["pending", "accepted", "excluded", "queried"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16))


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str] = mapped_column(String(200))
    business_age_years: Mapped[int] = mapped_column(Integer)
    requested_amount: Mapped[Decimal] = mapped_column(Money)
    purpose: Mapped[str] = mapped_column(String(300))
    tenor_months: Mapped[int] = mapped_column(Integer)
    annual_rate: Mapped[Decimal] = mapped_column(ExactDecimal)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    source: Mapped[str] = mapped_column(String(16), default="sme_portal")
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    accounts: Mapped[list["Account"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    bank_code: Mapped[str] = mapped_column(String(16))  # BBL, KBANK, SCB, KTB ...
    account_no_masked: Mapped[str] = mapped_column(String(32))
    account_name: Mapped[str] = mapped_column(String(200))
    account_type: Mapped[str] = mapped_column(String(32))  # savings, current
    owner_type: Mapped[str] = mapped_column(String(16))  # E2-15 ownership mapping

    case: Mapped[Case] = relationship(back_populates="accounts")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str] = mapped_column(String(100))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    # Decrypted copy for the viewer when the original is password-protected (password is never stored).
    view_path: Mapped[str | None] = mapped_column(String(500))
    parser: Mapped[str | None] = mapped_column(String(40))
    parse_report: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    case: Mapped[Case] = relationship(back_populates="documents")
    pages: Mapped[list["Page"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)  # 1-based
    width: Mapped[float] = mapped_column(Float)  # PDF points
    height: Mapped[float] = mapped_column(Float)

    document: Mapped[Document] = relationship(back_populates="pages")


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    page_id: Mapped[int | None] = mapped_column(ForeignKey("pages.id", ondelete="SET NULL"))
    row_index: Mapped[int] = mapped_column(Integer, default=0)

    posted_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    code: Mapped[str | None] = mapped_column(String(16))  # statement transaction code
    channel: Mapped[str | None] = mapped_column(String(32))
    debit: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    credit: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    balance: Mapped[Decimal | None] = mapped_column(Money)
    counterparty_name: Mapped[str | None] = mapped_column(String(200))
    counterparty_account: Mapped[str | None] = mapped_column(String(64))
    counterparty_bank: Mapped[str | None] = mapped_column(String(16))

    # Pixel lineage (E10-01): bbox in PDF points, origin top-left.
    bbox_x0: Mapped[float | None] = mapped_column(Float)
    bbox_y0: Mapped[float | None] = mapped_column(Float)
    bbox_x1: Mapped[float | None] = mapped_column(Float)
    bbox_y1: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    extractor_version: Mapped[str] = mapped_column(String(40), default="")

    # Engine outputs
    tag: Mapped[str | None] = mapped_column(String(40), index=True)
    tag_source: Mapped[str | None] = mapped_column(String(16))  # rule, llm, ca
    tier: Mapped[str | None] = mapped_column(String(20), index=True)
    loop_id: Mapped[str | None] = mapped_column(String(40), index=True)


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))  # promptbiz_sandbox, etax_upload
    invoice_no: Mapped[str] = mapped_column(String(64))
    issue_date: Mapped[date] = mapped_column(Date)
    buyer_name: Mapped[str] = mapped_column(String(200))
    buyer_tax_id: Mapped[str | None] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Money)  # total incl. VAT
    vat: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    settlement_ref: Mapped[str | None] = mapped_column(String(64))
    matched_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))


class TaxFiling(Base):
    __tablename__ = "tax_filings"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    sales: Mapped[Decimal] = mapped_column(Money)
    purchases: Mapped[Decimal] = mapped_column(Money)
    vat_payable: Mapped[Decimal] = mapped_column(Money)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))


class AltDataRecord(Base):
    __tablename__ = "alt_data"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # electricity, water, rent
    period: Mapped[str] = mapped_column(String(7))
    due_date: Mapped[date] = mapped_column(Date)
    paid_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    source: Mapped[str] = mapped_column(String(32), default="sandbox")


class WatchlistItem(Base):
    __tablename__ = "watchlist"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    suspicion_score: Mapped[float] = mapped_column(Float, default=0.5)
    system_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    reason: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEntry(Base):
    """Append-only, hash-chained audit log (E9-05)."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    ip: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
