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
    username: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16))
    password_hash: Mapped[str | None] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(default=True)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_name: Mapped[str] = mapped_column(String(200))
    tax_id: Mapped[str | None] = mapped_column(String(13))
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
    # Sandbox-only what-if for the utility connector (demo control; never on live data).
    sandbox_alt_scenario: Mapped[str] = mapped_column(String(32), default="clean")
    # Who owns and serves the application (E12/E13).
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    rm_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    submission_mode: Mapped[str] = mapped_column(String(16), default="fast_track")  # fast_track | rm_assisted | branch
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    tag_reason: Mapped[str | None] = mapped_column(Text)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL", use_alter=True))


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))  # promptbiz_sandbox, etax_upload
    invoice_no: Mapped[str] = mapped_column(String(64))
    issue_date: Mapped[date] = mapped_column(Date)
    buyer_name: Mapped[str] = mapped_column(String(200))
    buyer_tax_id: Mapped[str | None] = mapped_column(String(20))
    seller_tax_id: Mapped[str | None] = mapped_column(String(13))
    subtotal: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    vat: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    amount: Mapped[Decimal] = mapped_column(Money)  # total incl. VAT
    wht: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))  # withholding tax deducted by buyer
    paid_amount: Mapped[Decimal | None] = mapped_column(Money)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    settlement_ref: Mapped[str | None] = mapped_column(String(64))
    matched_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))


class TaxFiling(Base):
    __tablename__ = "tax_filings"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    sales: Mapped[Decimal] = mapped_column(Money)  # excl. VAT
    output_vat: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
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
    # Plain column, not a foreign key: audit rows must never be rewritten (e.g. SET NULL on delete).
    case_id: Mapped[int | None] = mapped_column(Integer, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime)  # naive UTC, exactly as hashed
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


class Analysis(Base):
    """One engine run over a case. `result` is the full aggregate output (JSON)."""

    __tablename__ = "analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    engine_version: Mapped[str] = mapped_column(String(32))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)


class TagOverride(Base):
    """A CA's override of the engine's classification for one transaction (E9-04)."""

    __tablename__ = "tag_overrides"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), unique=True)
    value: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LlmCache(Base):
    """LLM responses keyed by a hash of (provider, model, prompt, schema) (E7-01).

    Makes the demo reproducible and offline-capable: a response generated once is
    replayed instead of calling the API again.
    """

    __tablename__ = "llm_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(32))
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreditMemo(Base):
    """The 1-page credit memo for a case (E11): draft narrative, then CA sign-off + PDF."""

    __tablename__ = "credit_memos"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | signed
    narrative: Mapped[str] = mapped_column(Text, default="")
    narrative_source: Mapped[str] = mapped_column(String(16), default="template")  # llm | llm-cache | template | ca_edited
    recommendation: Mapped[str | None] = mapped_column(String(32))  # approve | approve_structured | decline
    approved_amount: Mapped[Decimal | None] = mapped_column(Money)
    trade_line_amount: Mapped[Decimal | None] = mapped_column(Money)
    ca_reason: Mapped[str | None] = mapped_column(Text)
    signed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("analyses.id", ondelete="SET NULL"))
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    audit_head: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Consent(Base):
    """Purpose-bound PDPA consent (E13-03, E14-02). Connectors refuse without a live grant."""

    __tablename__ = "consents"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(32))  # credit_assessment | promptbiz_data | utility_data
    granted: Mapped[bool] = mapped_column(default=True)
    version: Mapped[str] = mapped_column(String(16), default="v1")
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Query(Base):
    """A pinpoint question about one transaction (E12-04). CA -> RM, optionally forwarded to the SME."""

    __tablename__ = "queries"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    watchlist_item_id: Mapped[int | None] = mapped_column(ForeignKey("watchlist.id", ondelete="SET NULL"))
    audience: Mapped[str] = mapped_column(String(8), default="rm")  # rm | sme
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open | answered | closed
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    answer_note: Mapped[str | None] = mapped_column(Text)
    answered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Evidence(Base):
    """Photo/file evidence attached to a query or transaction (E12-05, E10-05)."""

    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    query_id: Mapped[int | None] = mapped_column(ForeignKey("queries.id", ondelete="SET NULL"))
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(500))
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)



class LlmCall(Base):
    """Every LLM attempt with the exact (masked) prompt it carried (E14-04 "what the AI saw")."""

    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int | None] = mapped_column(Integer, index=True)
    purpose: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16))  # live | cache | unavailable | error
    masked_system: Mapped[str] = mapped_column(Text)
    masked_prompt: Mapped[str] = mapped_column(Text)
    pii_counts: Mapped[dict[str, Any]] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)



class CreditPolicy(Base):
    """Versioned credit policy (E6-08); the newest row is in force."""

    __tablename__ = "credit_policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    min_dscr: Mapped[Decimal] = mapped_column(ExactDecimal)
    target_dscr: Mapped[Decimal] = mapped_column(ExactDecimal)
    max_dsr: Mapped[Decimal] = mapped_column(ExactDecimal)
    trade_line_ratio: Mapped[Decimal] = mapped_column(ExactDecimal)
    reason: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
