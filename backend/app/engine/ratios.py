"""Loan math, DSCR/DSR and safe-limit sizing (E6-02, E6-03, E6-04).

Deterministic Decimal arithmetic only. Formulas (ITMX.md, Responsible Lending §1):
  payment      = principal * r / (1 - (1 + r)^-n)          r = annual rate / 12
  DSCR         = clean operating cash flow (monthly) / total monthly debt service
  DSR          = total monthly debt service / clean operating cash flow (monthly)
  max new pmt  = CFO / target DSCR - existing debt service
  safe limit   = principal that pmt buys, rounded DOWN to the nearest 10,000 THB
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.engine.types import Policy

ZERO = Decimal("0")
TWO_DP = Decimal("0.01")


def pmt_factor(annual_rate: Decimal, months: int) -> Decimal:
    """Monthly payment per 1 THB of principal."""
    if months <= 0:
        raise ValueError("tenor must be positive")
    r = annual_rate / 12
    if r == 0:
        return Decimal(1) / months
    return r / (1 - (1 + r) ** -months)


def payment(principal: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    return (principal * pmt_factor(annual_rate, months)).quantize(TWO_DP, ROUND_HALF_UP)


def principal_for_payment(monthly_payment: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    if monthly_payment <= 0:
        return ZERO
    return monthly_payment / pmt_factor(annual_rate, months)


def dscr(cfo_monthly: Decimal, total_debt_service: Decimal) -> Decimal | None:
    return None if total_debt_service <= 0 else cfo_monthly / total_debt_service


def dsr(cfo_monthly: Decimal, total_debt_service: Decimal) -> Decimal | None:
    return None if cfo_monthly <= 0 else total_debt_service / cfo_monthly


def floor_to(amount: Decimal, step: Decimal = Decimal("10000")) -> Decimal:
    if amount <= 0:
        return ZERO
    return (amount / step).to_integral_value(ROUND_FLOOR) * step


def limit_at(cfo_monthly: Decimal, existing: Decimal, target_dscr: Decimal, annual_rate: Decimal,
             months: int) -> Decimal:
    """Largest principal (rounded down to 10,000) keeping DSCR >= target."""
    max_new = cfo_monthly / target_dscr - existing
    return floor_to(principal_for_payment(max_new, annual_rate, months))


@dataclass
class Sizing:
    amount: Decimal
    annual_rate: Decimal
    tenor_months: int
    cfo_monthly: Decimal
    existing_debt_monthly: Decimal
    new_payment: Decimal
    total_debt_service: Decimal
    dscr: Decimal | None
    dsr: Decimal | None
    passes_min: bool
    meets_target: bool
    safe_limit: Decimal  # at target DSCR
    max_at_min: Decimal  # at minimum DSCR
    policy: Policy


def size(amount: Decimal, cfo_monthly: Decimal, existing: Decimal, annual_rate: Decimal, months: int,
         policy: Policy) -> Sizing:
    new = payment(amount, annual_rate, months)
    total = existing + new
    d = dscr(cfo_monthly, total)
    return Sizing(
        amount=amount,
        annual_rate=annual_rate,
        tenor_months=months,
        cfo_monthly=cfo_monthly,
        existing_debt_monthly=existing,
        new_payment=new,
        total_debt_service=total,
        dscr=d,
        dsr=dsr(cfo_monthly, total),
        # Pass/fail uses the unrounded ratio; display rounds to 2 dp.
        passes_min=d is not None and d >= policy.min_dscr,
        meets_target=d is not None and d >= policy.target_dscr,
        safe_limit=limit_at(cfo_monthly, existing, policy.target_dscr, annual_rate, months),
        max_at_min=limit_at(cfo_monthly, existing, policy.min_dscr, annual_rate, months),
        policy=policy,
    )
