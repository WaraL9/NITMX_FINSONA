"""Typed loader for data/scenario_*.yaml (E1-01)."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings


class ScenarioCase(BaseModel):
    company_name: str
    company_name_en: str
    tax_id: str
    industry: str
    business_age_years: int
    purpose: str
    source: str
    period_start: date
    period_end: date
    months: int


class LoanRequest(BaseModel):
    amount: Decimal
    tenor_months: int
    annual_rate: Decimal
    type: str


class Policy(BaseModel):
    min_dscr: Decimal
    target_dscr: Decimal
    max_dsr: Decimal


class ScenarioAccount(BaseModel):
    key: str
    bank_code: str
    account_no_masked: str
    account_name: str
    account_type: str
    owner_type: str
    pdf_password: str | None = None


class Revenue(BaseModel):
    gross_raw_inflow: Decimal
    own_account_loops: Decimal
    owner_family_inflow: Decimal
    unverified_inflow: Decimal
    tiers: dict[str, Decimal]


class Costs(BaseModel):
    business_operating_6m: Decimal
    household_6m: Decimal


class LoopLeg(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    amount: Decimal
    at: datetime


class Loop(BaseModel):
    id: str
    description: str
    legs: list[LoopLeg]


class WatchlistSpec(BaseModel):
    date: date
    counterparty: str
    amount: Decimal
    description: str
    system_note: str
    demo_role: str


class Scenario(BaseModel):
    case: ScenarioCase
    loan_request: LoanRequest
    policy: Policy
    accounts: list[ScenarioAccount]
    revenue: Revenue
    costs: Costs
    existing_debt_service_monthly: Decimal
    loops: list[Loop]
    watchlist: list[WatchlistSpec]
    alt_data: dict[str, str]
    expected: dict[str, Decimal]


def load_scenario(name: str = "kitti", data_dir: Path | None = None) -> Scenario:
    path = (data_dir or settings.data_dir) / f"scenario_{name}.yaml"
    with path.open(encoding="utf-8") as f:
        return Scenario.model_validate(yaml.safe_load(f))
