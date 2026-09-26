"""Sandbox stand-ins for external APIs we cannot access (E3-02).

Served under /sandbox so they are never confused with the product API. They behave like
the real thing would (consent token required, realistic latency) so the demo can show the
integration end to end.
"""

import time

from fastapi import APIRouter, Header, HTTPException

from app.connectors.promptbiz import sandbox_invoices

router = APIRouter(prefix="/sandbox/promptbiz/v1", tags=["sandbox"])


@router.get("/sellers/{seller_tax_id}/invoices")
def promptbiz_invoices(seller_tax_id: str, x_consent_token: str | None = Header(None)) -> dict:
    if not x_consent_token:
        raise HTTPException(401, "X-Consent-Token header required (business owner's consent)")
    time.sleep(0.15)  # a remote API is never instant
    invoices = sandbox_invoices(seller_tax_id)
    return {"seller_tax_id": seller_tax_id, "count": len(invoices), "invoices": invoices, "mode": "sandbox"}
