"""API schemas (E0-03).

Money crosses the wire as a decimal STRING ("5000000.00") so JavaScript never
rounds it through a float. The frontend formats it for display only.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

MoneyStr = Annotated[Decimal, PlainSerializer(lambda d: f"{d:.2f}", return_type=str, when_used="json")]
DecimalStr = Annotated[Decimal, PlainSerializer(lambda d: str(d), return_type=str, when_used="json")]

CaseStatus = Literal["draft", "processing", "in_review", "decided"]
CaseSource = Literal["sme_portal", "rm", "branch"]
OwnerType = Literal["company", "director", "family", "external"]


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    bank_code: str
    account_no_masked: str
    account_name: str
    account_type: str
    owner_type: OwnerType


class CaseBase(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    industry: str
    business_age_years: int = Field(ge=0)
    requested_amount: MoneyStr = Field(gt=0)
    purpose: str
    tenor_months: int = Field(gt=0, le=360)
    annual_rate: DecimalStr = Field(ge=0, lt=1)


class CaseCreate(CaseBase):
    source: CaseSource = "sme_portal"


class CaseSummary(CaseBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: CaseStatus
    source: CaseSource
    created_at: datetime


class CaseDetail(CaseSummary):
    period_start: date | None
    period_end: date | None
    accounts: list[AccountOut]


class Health(BaseModel):
    status: Literal["ok"]
    version: str
    connector_mode: str
    live_ocr: bool
    live_llm: bool


class ParseReport(BaseModel):
    parser: str
    parser_version: str
    rows: int
    pages: int
    bank_code: str | None
    account_no: str | None
    account_name: str | None
    period_start: date | None
    period_end: date | None
    opening_balance: str | None
    closing_balance: str | None
    total_debit: str
    total_credit: str
    continuity_ok: bool
    continuity_breaks: list[int]
    was_encrypted: bool
    account_created: bool
    warnings: list[str]


DocumentKind = Literal["statement", "pp30", "etax_invoice", "utility_bill", "evidence"]


class PP30ParseReport(BaseModel):
    parser: str
    parser_version: str
    tax_id: str
    period: str
    amounts: dict[str, str]
    bboxes: dict[str, list[float]]
    warnings: list[str]


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    account_id: int | None
    kind: DocumentKind
    filename: str
    sha256: str
    page_count: int
    uploaded_at: datetime
    parse_report: ParseReport | PP30ParseReport | None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: int
    document_id: int | None
    page_no: int | None
    row_index: int
    posted_at: datetime
    code: str | None
    channel: str | None
    description: str
    debit: MoneyStr
    credit: MoneyStr
    balance: MoneyStr | None
    counterparty_name: str | None
    counterparty_bank: str | None
    counterparty_account: str | None
    bbox: list[float] | None = Field(description="[x0, top, x1, bottom] in PDF points, top-left origin")
    confidence: float
    extractor_version: str
    tag: str | None = None
    tier: str | None = None
    loop_id: str | None = None
    tag_reason: str | None = None
    tag_source: str | None = None


class TransactionPage(BaseModel):
    total: int
    sum_debit: str = "0.00"
    sum_credit: str = "0.00"
    offset: int
    limit: int
    items: list[TransactionOut]


class ApiError(BaseModel):
    code: str
    message: str
    existing_document_id: int | None = None


# ---------- analysis ----------

class Waterfall(BaseModel):
    gross_raw_inflow: str
    own_account_loops: str
    internal_transfers: str
    owner_family_inflow: str
    unverified_pending: str
    unverified_excluded: str
    accepted_by_ca: str
    ca_non_revenue: str = "0.00"
    verified_operating_revenue: str


class Tiers(BaseModel):
    T1_golden: str
    T2_tax: str
    T3_operational: str
    T4_unverified: str


class LoopLegOut(BaseModel):
    debit_txn_id: int
    credit_txn_id: int
    from_account_id: int
    to_account_id: int
    amount: str
    at: datetime


class LoopOut(BaseModel):
    id: str
    netted_amount: str
    hours: float
    legs: list[LoopLegOut]


class AnalysisOut(BaseModel):
    id: int
    created_at: datetime
    engine_version: str
    duration_ms: int
    period_start: date
    period_end: date
    months: int
    reconciles: bool
    notes: list[str]
    waterfall: Waterfall
    tiers: Tiers
    costs: dict[str, str]
    clean_cash_flow_period: str
    clean_cash_flow_monthly: str
    existing_debt_monthly: str
    loops: list[LoopOut]
    watchlist_count: int
    connector: dict | None
    timings_ms: dict[str, float] = {}


class PolicyOut(BaseModel):
    min_dscr: DecimalStr
    target_dscr: DecimalStr
    max_dsr: DecimalStr


class SizingOut(BaseModel):
    amount: MoneyStr
    annual_rate: DecimalStr
    tenor_months: int
    cfo_monthly: MoneyStr
    existing_debt_monthly: MoneyStr
    new_payment: MoneyStr
    total_debt_service: MoneyStr
    dscr: str | None = Field(description="4 dp; pass/fail uses the unrounded value")
    dsr: str | None
    passes_min: bool
    meets_target: bool
    safe_limit: MoneyStr
    max_at_min: MoneyStr
    policy: PolicyOut


class WatchlistOut(BaseModel):
    id: int
    status: Literal["pending", "accepted", "excluded", "queried"]
    suspicion_score: float
    system_note: str
    reason: str | None
    transaction: TransactionOut


# ---------- people, decisions, overrides, audit, lineage ----------

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    role: Literal["CA", "RM", "SME", "AUDITOR"]


WatchlistAction = Literal["accept", "exclude", "query_rm", "reopen"]


class DecisionIn(BaseModel):
    action: WatchlistAction
    reason: str = Field(min_length=10, max_length=2000, description="professional reasoning, required")


class ReasonIn(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


class DecisionOut(BaseModel):
    item: WatchlistOut
    analysis: AnalysisOut


OverrideValue = Literal["T1_golden", "T2_tax", "T3_operational", "T4_unverified", "non_revenue", "business_cost",
                        "non_business"]


class OverrideIn(BaseModel):
    value: OverrideValue
    reason: str = Field(min_length=10, max_length=2000)


class OverrideOut(BaseModel):
    transaction: TransactionOut
    analysis: AnalysisOut


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int | None
    ts: datetime
    user_id: int | None
    user_name: str | None = None
    ip: str | None
    action: str
    target_type: str | None
    target_id: str | None
    before: dict | None
    after: dict | None
    reason: str | None
    prev_hash: str
    hash: str


class ChainStatusOut(BaseModel):
    ok: bool
    entries: int
    first_bad_id: int | None
    detail: str | None


class DocumentVerifyOut(BaseModel):
    document_id: int
    filename: str
    recorded_sha256: str
    current_sha256: str
    verified: bool


class LineageOut(BaseModel):
    transaction: TransactionOut
    document: DocumentOut | None
    page_width: float | None
    page_height: float | None
    sha256_verified: bool | None
