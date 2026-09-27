"""API schemas (E0-03).

Money crosses the wire as a decimal STRING ("5000000.00") so JavaScript never
rounds it through a float. The frontend formats it for display only.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

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
    demo_mode: bool = False


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
    duplicate_rows_skipped: int = 0
    duplicate_pages: list[int] = []
    ocr: "OcrReport | None" = None


class OcrReport(BaseModel):
    provider: str
    model: str
    words: int
    mean_confidence: float
    threshold: float
    review_pending: int = 0


DocumentKind = Literal["statement", "pp30", "etax_invoice", "utility_bill", "evidence"]


class PP30ParseReport(BaseModel):
    parser: str
    parser_version: str
    tax_id: str
    period: str
    amounts: dict[str, str]
    bboxes: dict[str, list[float]]
    warnings: list[str]


class ETaxParseReport(BaseModel):
    """E2-13: what was read from an e-Tax invoice (XML, PDF with embedded XML, or PDF text)."""
    parser: str
    parser_version: str
    source: Literal["xml", "pdf_embedded_xml", "pdf_text"]
    invoice_no: str
    type_code: str
    type_name: str
    issue_date: date
    seller_name: str
    seller_tax_id: str | None
    buyer_name: str
    buyer_tax_id: str | None
    currency: str
    amounts: dict[str, str] = Field(description="subtotal (excl. VAT), vat, total — decimal strings")
    bboxes: dict[str, list[float]]
    signature: Literal["present_unverified", "absent"]
    warnings: list[str]


class InvoiceLinkOut(BaseModel):
    """Where an uploaded e-Tax invoice ended up after the last analysis."""
    invoice_no: str
    status: Literal["pending_analysis", "matched", "unmatched", "duplicate_of_promptbiz"]
    transaction_id: int | None = None
    paid_at: datetime | None = None
    paid_amount: MoneyStr | None = None


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
    parse_report: ParseReport | PP30ParseReport | ETaxParseReport | None
    invoice: InvoiceLinkOut | None = None


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
    review_status: Literal["pending", "confirmed", "corrected"] | None = None
    review_reasons: list[str] | None = None
    ocr_fields: dict[str, float] | None = Field(default=None, description="OCR confidence per key field")


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
    etax: "ETaxSummaryOut | None" = None
    timings_ms: dict[str, float] = {}
    ocr_held: dict[str, Any] | None = Field(default=None, description="OCR rows held out of the math pending review")
    concentration: "ConcentrationOut | None" = None
    anomalies: "list[AnomalyOut]" = []
    revenue_monthly: str | None = None
    costs_monthly: str | None = None
    t1_monthly: str | None = None
    sizing_cfo_monthly: str | None = None
    alt_data: "AltDataOut | None" = None
    alt_connector: dict | None = None
    cash_pattern: "CashPatternOut | None" = None
    drivers: list["DriverOut"] = []


class ETaxSummaryOut(BaseModel):
    uploaded: int
    matched: int
    duplicates_of_promptbiz: list[str] = Field(description="invoice numbers also on PromptBiz — only the network copy is used")


class PolicyOut(BaseModel):
    min_dscr: DecimalStr
    target_dscr: DecimalStr
    max_dsr: DecimalStr


class StructureOut(BaseModel):
    needed: bool
    term_loan: MoneyStr
    trade_line: MoneyStr
    total: MoneyStr
    shortfall: MoneyStr
    trade_line_ratio: DecimalStr


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
    haircut: DecimalStr
    stressed: bool
    revenue_drop: DecimalStr
    cost_rise: DecimalStr
    rate_rise_bp: int
    structure: StructureOut


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
    username: str
    name: str
    role: Literal["CA", "RM", "SME", "AUDITOR"]


WatchlistAction = Literal["accept", "exclude", "query_rm", "reopen"]


class DecisionIn(BaseModel):
    action: WatchlistAction
    reason: str = Field(min_length=10, max_length=2000, description="professional reasoning, required")


class ReasonIn(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


class CustomerShareOut(BaseModel):
    name: str
    amount: str
    share: str
    receipts: int
    months_active: int
    txn_ids: list[int]


class ConcentrationOut(BaseModel):
    """E5-06: who the verified revenue comes from."""
    identified: str
    unidentified: str
    customers: int
    top1_share: str
    top5_share: str
    hhi: int
    level: Literal["low", "moderate", "high"]
    flags: list[str]
    top: list[CustomerShareOut]


class AnomalyOut(BaseModel):
    """E4-09: informational pattern flags; they never change a figure."""
    kind: Literal["pass_through", "period_end", "revenue_spike", "round_cash"]
    severity: Literal["info", "watch", "high"]
    title: str
    detail: str
    amount: str
    txn_ids: list[int]


class AccountCoverageOut(BaseModel):
    account_id: int
    label: str
    owner_type: str
    documents: int
    covered: list[list[date]]
    gaps: list[list[date]]
    missing_days: int


class CoverageOut(BaseModel):
    period_start: date | None
    period_end: date | None
    complete: bool
    accounts: list[AccountCoverageOut]


class OcrReviewIn(BaseModel):
    action: Literal["confirm", "correct"]
    debit: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    credit: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    balance: Decimal | None = Field(default=None, max_digits=15, decimal_places=2)
    reason: str | None = Field(default=None, max_length=2000)


class OcrReviewOut(BaseModel):
    txn: TransactionOut
    changed: bool
    pending_left: int
    analysis: AnalysisOut


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



class AltDataOut(BaseModel):
    months_covered: int
    bills: int
    on_time: int
    late_30: int
    late_60_or_unpaid: int
    haircut: str
    ews: bool
    liveness_confirmed: bool
    signals: list[str]


class CashPatternOut(BaseModel):
    detected: bool
    count: int
    total: str
    average: str
    top_weekdays: list[str]
    weekday_share: float
    morning_share: float


class DriverOut(BaseModel):
    kind: Literal["positive", "risk", "info"]
    key: str
    title: str
    detail: str
    impact: str
    metric: str | None


class AltScenarioIn(BaseModel):
    scenario: Literal["clean", "late_electricity_twice"]


AnalysisOut.model_rebuild()


# ---------- credit memo ----------

class MemoStructure(BaseModel):
    needed: bool
    term_loan: str
    trade_line: str
    total: str
    shortfall: str
    trade_line_ratio: str


class MemoSizing(BaseModel):
    amount: str
    dscr: str
    new_payment: str
    passes_min: bool
    meets_target: bool
    safe_limit: str
    max_at_min: str
    policy: dict[str, str]
    structure: MemoStructure


class MemoWatch(BaseModel):
    id: int
    txn_id: int
    date: str
    counterparty: str | None
    amount: str
    status: Literal["pending", "accepted", "excluded", "queried"]
    reason: str | None
    decided_by: str | None


class MemoCase(BaseModel):
    id: int
    company_name: str
    industry: str
    business_age_years: int
    requested_amount: str
    purpose: str
    tenor_months: int
    annual_rate: str
    status: CaseStatus


class MemoState(BaseModel):
    id: int
    status: Literal["draft", "signed"]
    narrative: str
    narrative_source: Literal["llm", "llm-cache", "template", "ca_edited"]
    recommendation: Literal["approve", "approve_structured", "decline"] | None
    approved_amount: str | None
    trade_line_amount: str | None
    ca_reason: str | None
    signed_by: str | None
    signed_at: str | None
    analysis_id: int | None
    pdf_sha256: str | None
    audit_head: str | None
    has_pdf: bool
    los_reference: str | None = None
    los_submitted_at: str | None = None


class MemoPackageOut(BaseModel):
    case: MemoCase
    analysis: AnalysisOut
    sizing_request: MemoSizing
    sizing_safe: MemoSizing
    watchlist: list[MemoWatch]
    documents: int
    memo: MemoState


class LosSubmitOut(BaseModel):
    reference: str
    submitted_at: str
    payload_sha256: str
    mode: Literal["sandbox", "live"]
    already_submitted: bool


class NarrativeIn(BaseModel):
    narrative: str = Field(min_length=20, max_length=6000)


class SignIn(BaseModel):
    recommendation: Literal["approve", "approve_structured", "decline"]
    approved_amount: MoneyStr | None = None
    trade_line_amount: MoneyStr | None = None
    reason: str = Field(min_length=10, max_length=2000)


class LlmStatusOut(BaseModel):
    live: bool
    provider: str
    model: str
    note: str | None


# ---------- field: queries, evidence, RM, SME ----------

class EvidenceOut(BaseModel):
    id: int
    filename: str
    mime: str
    size: int
    sha256: str
    uploaded_by: str | None
    uploaded_at: datetime


class QueryOut(BaseModel):
    id: int
    case_id: int
    transaction_id: int
    watchlist_item_id: int | None
    audience: Literal["rm", "sme"]
    question: str
    status: Literal["open", "answered", "closed"]
    created_by: str | None
    created_at: datetime
    answer_note: str | None
    answered_by: str | None
    answered_at: datetime | None
    amount: str
    txn_date: str
    counterparty: str | None
    description: str
    evidence: list[EvidenceOut]


class ForwardIn(BaseModel):
    note: str | None = Field(None, max_length=1000)


class GapOut(BaseModel):
    kind: Literal["data", "evidence", "structure", "risk", "consent", "opportunity"]
    title: str
    starter: str
    impact: str | None


class LeadOut(BaseModel):
    case_id: int
    company_name: str
    industry: str
    requested_amount: MoneyStr
    status: CaseStatus
    submission_mode: str
    contact_phone: str | None
    score: int
    group: Literal["ready", "restructure", "needs_data"]
    reasons: list[str]
    dscr_at_request: str | None
    safe_limit: str | None
    open_queries: int


class LeadDetailOut(LeadOut):
    gaps: list[GapOut]
    queries: list[QueryOut]


class IndustryOut(BaseModel):
    key: str
    label: str


class PrequalIn(BaseModel):
    requested_amount: MoneyStr = Field(gt=0, le=Decimal("100000000"))
    industry: str
    monthly_revenue: MoneyStr = Field(gt=0)
    existing_debt_monthly: MoneyStr = Field(Decimal("0"), ge=0)
    annual_rate: DecimalStr = Field(Decimal("0.07"), ge=0, lt=1)
    tenor_months: int = Field(12, gt=0, le=120)


class PrequalOut(BaseModel):
    result: Literal["high", "conditional", "mismatch"]
    indicative_cfo: MoneyStr
    dscr: str | None
    safe_limit: MoneyStr
    reasons: list[str]
    unlocks: list[str]
    disclaimer: str


class ConsentState(BaseModel):
    purpose: str
    label: str
    granted: bool
    recorded_at: datetime | None


class ApplicationIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    tax_id: str = Field(pattern=r"^\d{13}$")
    industry: str
    business_age_years: int = Field(ge=0, le=200)
    requested_amount: MoneyStr = Field(gt=0, le=Decimal("100000000"))
    purpose: str = Field(min_length=2, max_length=300)
    tenor_months: int = Field(12, gt=0, le=120)
    mode: Literal["fast_track", "rm_assisted"]
    contact_phone: str = Field(pattern=r"^[0-9+\- ]{9,20}$")
    consents: dict[str, bool]


class TrackerStage(BaseModel):
    key: str
    label: str
    status: Literal["done", "current", "todo"]


class TrackerOut(BaseModel):
    stages: list[TrackerStage]
    sla_due: str | None
    sla_hours_left: float | None
    outcome: dict | None


class ApplicationOut(BaseModel):
    case_id: int
    company_name: str
    industry: str
    requested_amount: MoneyStr
    purpose: str
    tenor_months: int
    status: CaseStatus
    submission_mode: str
    submitted_at: datetime | None
    documents: int
    tracker: TrackerOut
    consents: list[ConsentState]
    questions: list[QueryOut]



class LlmCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    purpose: str
    provider: str
    model: str
    outcome: Literal["live", "cache", "unavailable", "error"]
    masked_system: str
    masked_prompt: str
    pii_counts: dict[str, int]
    note: str | None
    created_at: datetime



class PolicyIn(BaseModel):
    min_dscr: DecimalStr | None = None
    target_dscr: DecimalStr | None = None
    max_dsr: DecimalStr | None = None
    trade_line_ratio: DecimalStr | None = None
    reason: str = Field(min_length=10, max_length=2000)


class PolicyVersionOut(BaseModel):
    id: int
    min_dscr: str
    target_dscr: str
    max_dsr: str
    trade_line_ratio: str
    reason: str | None
    updated_by: str | None
    updated_at: datetime


class PolicyStateOut(BaseModel):
    current: dict[str, str]
    history: list[PolicyVersionOut]
