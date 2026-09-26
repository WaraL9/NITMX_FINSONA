"""Utility & rent payment history connector (E3-05).

Real sources (MEA/PEA, waterworks, landlord records) need data-sharing agreements we don't
have, so the sandbox serves a synthetic feed with the same shape. The sandbox supports a
what-if scenario switch so the early-warning rules can be demonstrated live.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.connectors.base import ConnectorError, ConsentMissing
from app.synth.alt_data import SCENARIOS


@lru_cache(maxsize=8)
def _load(path: Path, mtime: float) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sandbox_bills(tax_id: str, scenario: str = "clean") -> list[dict]:
    if scenario not in SCENARIOS:
        raise ConnectorError(f"unknown sandbox scenario {scenario!r}")
    for path in sorted(settings.data_dir.glob("generated/*/alt_data.json")):
        data = _load(path, path.stat().st_mtime)
        if data["tax_id"] == tax_id:
            return data["scenarios"][scenario]
    return []


class UtilitySandbox:
    name = "Utility & Rent"
    mode = "sandbox"

    def fetch_bills(self, tax_id: str, consent_token: str, scenario: str = "clean") -> list[dict]:
        if not consent_token:
            raise ConsentMissing("utility data requires the business owner's consent")
        return sandbox_bills(tax_id, scenario)


def get_utility_source() -> UtilitySandbox:
    if settings.connector_mode == "live":
        raise ConnectorError("live utility data is not available; set FINSONA_CONNECTOR_MODE=sandbox")
    return UtilitySandbox()
