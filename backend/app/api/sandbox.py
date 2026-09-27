"""Sandbox stand-ins for external APIs we cannot access (E3-02).

Served under /sandbox so they are never confused with the product API. They behave like
the real thing would (consent token required, realistic latency) so the demo can show the
integration end to end.
"""

import time

from fastapi import APIRouter, Header, HTTPException

from app.connectors.base import ConnectorError
from app.connectors.promptbiz import sandbox_invoices
from app.connectors.utility import sandbox_bills

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


@router.get("/utility/v1/customers/{tax_id}/bills")
def utility_bills(tax_id: str, scenario: str = "clean", x_consent_token: str | None = Header(None)) -> dict:
    if not x_consent_token:
        raise HTTPException(401, "X-Consent-Token header required (business owner's consent)")
    try:
        bills = sandbox_bills(tax_id, scenario)
    except ConnectorError as e:
        raise HTTPException(422, str(e)) from e
    return {"tax_id": tax_id, "scenario": scenario, "count": len(bills), "bills": bills, "mode": "sandbox"}


@router.get("/promptbiz/v1/sellers/{seller_tax_id}/invoices")
def promptbiz_invoices(seller_tax_id: str, x_consent_token: str | None = Header(None)) -> dict:
    if not x_consent_token:
        raise HTTPException(401, "X-Consent-Token header required (business owner's consent)")
    time.sleep(0.15)  # a remote API is never instant
    invoices = sandbox_invoices(seller_tax_id)
    return {"seller_tax_id": seller_tax_id, "count": len(invoices), "invoices": invoices, "mode": "sandbox"}


@router.post("/los/v1/applications")
def los_applications(payload: dict, x_api_key: str | None = Header(None)) -> dict:
    """Stand-in for the bank's loan origination system: validates and books the decision."""
    if not x_api_key:
        raise HTTPException(401, "X-Api-Key header required")
    from app.connectors.los import get_los_target
    from app.db import SessionLocal

    with SessionLocal() as db:
        try:
            ref, again = get_los_target().submit(db, payload)
        except ConnectorError as e:
            raise HTTPException(422, str(e)) from e
        db.commit()
    return {"reference": ref, "status": "duplicate" if again else "received", "mode": "sandbox"}
