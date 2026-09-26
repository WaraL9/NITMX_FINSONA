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
