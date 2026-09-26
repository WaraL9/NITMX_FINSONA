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
    parse_report: ParseReport | None


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


class TransactionPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[TransactionOut]


class ApiError(BaseModel):
    code: str
    message: str
    existing_document_id: int | None = None
