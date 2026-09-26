"""Synthetic case bank (E15-01).

Variants of the canonical scenario with different business sizes (0.6x-2.0x revenue and
costs), existing debt, which transfer loops are present, watchlist amounts and random
seeds, so the engine is evaluated on many cases with known ground truth rather than
tuned to one. Owner money and household spending keep their canonical amounts (the
generator pins them), which is realistic: they don't scale with business size.
"""

from __future__ import annotations

import random
from decimal import ROUND_HALF_UP, Decimal

from app.scenario import Scenario, load_scenario

D = Decimal


def _q(v: Decimal, step: str = "1000") -> Decimal:
    s = D(step)
    return ((v / s).to_integral_value(ROUND_HALF_UP) * s).quantize(D("0.01"))


def variant(base: Scenario, rng: random.Random, idx: int) -> tuple[Scenario, int, float]:
    scale = D(str(round(rng.uniform(0.6, 2.0), 2)))
    sc = base.model_copy(deep=True)
    tiers = {k: _q(v * scale) for k, v in base.revenue.tiers.items()}
    sc.revenue.tiers = tiers

    # Keep a random non-empty subset of loops, scaled.
    loops = [lp.model_copy(deep=True) for lp in base.loops]
    keep = rng.sample(loops, rng.randint(1, len(loops)))
    for lp in keep:
        for leg in lp.legs:
            leg.amount = _q(leg.amount * scale, "1")
    sc.loops = keep
    company = {a.key for a in sc.accounts if a.owner_type == "company"}
    sc.revenue.own_account_loops = sum((leg.amount for lp in keep for leg in lp.legs if leg.to in company), D("0.00"))

    for w in sc.watchlist:
        w.amount = _q(w.amount * scale)
    sc.revenue.unverified_inflow = sum((w.amount for w in sc.watchlist), D("0.00"))
    sc.revenue.gross_raw_inflow = (sum(tiers.values(), D("0.00")) + sc.revenue.own_account_loops
                                   + sc.revenue.owner_family_inflow + sc.revenue.unverified_inflow)
    sc.costs.business_operating_6m = _q(base.costs.business_operating_6m * scale, "1")
    sc.existing_debt_service_monthly = _q(base.existing_debt_service_monthly * scale * D(str(rng.uniform(0.5, 1.5))), "1")
    sc.loan_request.amount = _q(base.loan_request.amount * scale, "10000")
    sc.expected = {}
    return sc, rng.randint(1, 10_000), float(scale)


def case_bank(n: int = 50, seed: int = 2026) -> list[tuple[str, Scenario, int, float]]:
    """(name, scenario, generator seed, scale). Case 0 is the canonical demo case."""
    base = load_scenario("kitti")
    rng = random.Random(seed)
    out = [("kitti", base, 42, 1.0)]
    for i in range(1, n):
        sc, gseed, scale = variant(base, rng, i)
        out.append((f"variant_{i:02d}", sc, gseed, scale))
    return out
