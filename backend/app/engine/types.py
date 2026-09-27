"""Engine data types. The engine is pure: plain dataclasses in, plain dataclasses out.

No database, no network, no LLM. Every figure the engine produces is a deterministic
function of these inputs, so it can be unit-tested and traced back to source rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

ENGINE_VERSION = "engine-2.1"

Tier = Literal["T1_golden", "T2_tax", "T3_operational", "T4_unverified"]
Decision = Literal["accepted", "excluded"]

# CA overrides (E9-04): company-account credits can be re-tiered or marked non-revenue;
# company-account debits can be counted in or out of business costs.
CREDIT_OVERRIDES = ("T1_golden", "T2_tax", "T3_operational", "T4_unverified", "non_revenue")
DEBIT_OVERRIDES = ("business_cost", "non_business")


@dataclass(frozen=True)
class EAccount:
    id: int
    bank_code: str
    account_no: str
    account_name: str
    owner_type: str  # company | director | family | external


@dataclass(frozen=True)
class ETxn:
    id: int
    account_id: int
    posted_at: datetime
    code: str
    description: str
    debit: Decimal
    credit: Decimal
    counterparty_name: str | None = None
    counterparty_account: str | None = None
    counterparty_bank: str | None = None


@dataclass(frozen=True)
class EInvoice:
    id: int
    invoice_no: str
    issue_date: date
    buyer_name: str
    total: Decimal
    subtotal: Decimal
    source: str = "promptbiz"  # promptbiz_* (network) | etax_upload (SME-provided e-Tax invoice)


@dataclass(frozen=True)
class EFiling:
    period: str  # YYYY-MM
    sales: Decimal  # excl. VAT
    output_vat: Decimal


@dataclass(frozen=True)
class Policy:
    min_dscr: Decimal = Decimal("1.25")
    target_dscr: Decimal = Decimal("1.35")
    max_dsr: Decimal = Decimal("0.80")
    # Trade Line (E6-07): self-liquidating invoice financing settled through PromptBiz,
    # sized as a share of average monthly Golden (invoice-matched) receipts.
    trade_line_ratio: Decimal = Decimal("0.40")
    trade_line_step: Decimal = Decimal("100000")


@dataclass
class Outcome:
    """What the engine concluded about one transaction, and why."""

    tag: str
    reason: str
    tier: Tier | None = None
    loop_id: str | None = None
    invoice_id: int | None = None
    overridden: bool = False


@dataclass
class LoopLeg:
    debit_txn_id: int
    credit_txn_id: int
    from_account_id: int
    to_account_id: int
    amount: Decimal
    at: datetime


@dataclass
class DetectedLoop:
    id: str
    legs: list[LoopLeg]
    netted_amount: Decimal  # credit legs landing in company accounts
    hours: float


@dataclass
class WatchItem:
    txn_id: int
    score: float
    note: str


@dataclass
class AnalysisResult:
    engine_version: str
    months: int
    outcomes: dict[int, Outcome]
    loops: list[DetectedLoop]
    watchlist: list[WatchItem]
    waterfall: dict[str, Decimal]
    tiers: dict[str, Decimal]
    costs: dict[str, Decimal]
    clean_cash_flow_period: Decimal
    clean_cash_flow_monthly: Decimal
    existing_debt_monthly: Decimal
    reconciles: bool
    notes: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
