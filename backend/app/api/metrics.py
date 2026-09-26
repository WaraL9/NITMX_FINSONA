"""Lineage for aggregate figures (E10-01): which transactions make up each number.

Each analysis figure maps to a filter over the tagged transactions. The invariant (tested)
is that summing the rows a filter returns reproduces the figure exactly, so clicking any
number on screen can list every row behind it.
"""

from app.engine.rules import COST_TAGS
from app.models import Account, Transaction

COMPANY = Account.owner_type == "company"
CREDIT = Transaction.credit > 0
DEBIT = Transaction.debit > 0
REVENUE_TIERS = ("T1_golden", "T2_tax", "T3_operational")
ALL_COST_TAGS = tuple(COST_TAGS | {"ca_business_cost"})


def _cost(tag: str):
    return [COMPANY, DEBIT, Transaction.tag == tag]


METRICS = {
    # waterfall (company-account credits)
    # OCR rows held for review (E2-09) are outside every figure until checked.
    "gross_raw_inflow": [COMPANY, CREDIT, Transaction.tag != "ocr_pending"],
    "own_account_loops": [COMPANY, CREDIT, Transaction.tag == "own_transfer_loop"],
    "internal_transfers": [COMPANY, CREDIT, Transaction.tag == "own_transfer_internal"],
    "owner_family_inflow": [COMPANY, CREDIT, Transaction.tag == "owner_injection"],
    "unverified_pending": [COMPANY, CREDIT, Transaction.tier == "T4_unverified", Transaction.tag != "ca_excluded"],
    "unverified_excluded": [COMPANY, CREDIT, Transaction.tag == "ca_excluded"],
    "accepted_by_ca": [COMPANY, CREDIT, Transaction.tag == "ca_accepted"],
    "ca_non_revenue": [COMPANY, CREDIT, Transaction.tag == "ca_non_revenue"],
    "verified_operating_revenue": [COMPANY, CREDIT, Transaction.tier.in_(REVENUE_TIERS)],
    # tiers
    **{k: [COMPANY, CREDIT, Transaction.tier == k] for k in (*REVENUE_TIERS, "T4_unverified")},
    # costs (company-account debits)
    "business_operating": [COMPANY, DEBIT, Transaction.tag.in_(ALL_COST_TAGS)],
    **{f"cost_{k}": _cost(k) for k in ALL_COST_TAGS},
    "household": [COMPANY, DEBIT, Transaction.tag.in_(("household", "owner_drawing"))],
    "debt_service_total": _cost("debt_service"),
}


def metric_filters(metric: str) -> list:
    return list(METRICS[metric])
