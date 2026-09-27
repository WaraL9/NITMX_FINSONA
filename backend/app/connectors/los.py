"""Loan origination system hand-off (E3-06).

The bank's LOS is where an approved credit becomes a booked loan. We cannot reach a real
one, so the sandbox stands in with the same contract a live adapter would have: accept a
versioned decision payload, validate it, and return the LOS reference number. Submitting
the same payload twice returns the same reference (idempotent), so a retry after a
timeout never books a loan twice.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connectors.base import ConnectorError, Mode
from app.models import LosInbox

SCHEMA = "finsona.los-export/v1"
REQUIRED = ("schema", "case", "decision", "figures", "evidence")


def canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class LosTarget(Protocol):
    name: str
    mode: Mode

    def submit(self, db: Session, payload: dict[str, Any]) -> tuple[str, bool]: ...


class LosSandbox:
    name = "los_sandbox"
    mode: Mode = "sandbox"

    def submit(self, db: Session, payload: dict[str, Any]) -> tuple[str, bool]:
        """Returns (reference, already_received)."""
        missing = [k for k in REQUIRED if k not in payload]
        if missing:
            raise ConnectorError(f"LOS rejected the payload: missing {', '.join(missing)}")
        if payload["schema"] != SCHEMA:
            raise ConnectorError(f"LOS rejected the payload: unsupported schema {payload['schema']!r}")
        if not payload["evidence"].get("memo_pdf_sha256"):
            raise ConnectorError("LOS rejected the payload: a signed credit memo is required")
        sha = hashlib.sha256(canonical(payload)).hexdigest()
        existing = db.scalar(select(LosInbox).where(LosInbox.payload_sha256 == sha))
        if existing:
            return existing.reference, True
        n = (db.scalar(select(func.count()).select_from(LosInbox)) or 0) + 1
        ref = f"LOS-{datetime.now(timezone.utc):%Y}-{n:06d}"
        db.add(LosInbox(reference=ref, payload_sha256=sha, payload=payload))
        db.flush()
        return ref, False


def get_los_target() -> LosTarget:
    return LosSandbox()
