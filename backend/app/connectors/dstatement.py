"""dStatement connector (E3-04): pull an account's statement straight from the bank.

dStatement lets a customer's own bank send their account statement to another bank,
with the customer's consent, as signed data instead of a PDF that could have been edited.
We have no access to the live network, so the sandbox serves a synthetic feed with the
statement schema a live adapter would return, signed the way a source bank would sign it
(HMAC-SHA256 here; a live adapter would verify the bank's certificate instead).
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings
from app.connectors.base import ConnectorError, ConsentMissing

SANDBOX_FEEDS = "generated/*/dstatement.json"
SANDBOX_KEY_ID = "SANDBOX-BANK-KEY-1"


class AccountNotFound(ConnectorError):
    pass


@dataclass
class SignedStatement:
    statement: dict[str, Any]
    signature: str
    key_id: str

    def to_bytes(self) -> bytes:
        """The document as delivered — what is fingerprinted and kept."""
        return json.dumps({"statement": self.statement, "signature": self.signature, "key_id": self.key_id},
                          ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")


def canonical(statement: dict[str, Any]) -> bytes:
    return json.dumps(statement, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(statement: dict[str, Any]) -> str:
    return hmac.new(settings.dstatement_sandbox_key.encode(), canonical(statement), hashlib.sha256).hexdigest()


def verify(s: SignedStatement) -> bool:
    return s.key_id == SANDBOX_KEY_ID and hmac.compare_digest(sign(s.statement), s.signature)


@lru_cache(maxsize=8)
def _load(path: Path, mtime: float) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _last4(account_no: str) -> str:
    digits = re.findall(r"\d", account_no)
    return "".join(digits[-4:])


def sandbox_statement(tax_id: str, bank_code: str, account_no: str, start: date | None = None,
                      end: date | None = None) -> SignedStatement:
    """The source bank's side: find the account held by this business and sign the statement."""
    for path in sorted(settings.data_dir.glob(SANDBOX_FEEDS)):
        feed = _load(path, path.stat().st_mtime)
        if feed["tax_id"] != tax_id:
            continue
        for acct in feed["accounts"]:
            if acct["bank_code"] == bank_code.upper() and _last4(acct["account_no"]) == _last4(account_no):
                # A copy: callers must never be able to alter the cached feed.
                return SignedStatement(copy.deepcopy(_window(acct, start, end)), "", SANDBOX_KEY_ID)
    raise AccountNotFound(f"ธนาคาร {bank_code} ไม่พบบัญชี {account_no} ของผู้ประกอบการรายนี้ (หรือไม่ได้ให้ความยินยอม)")


def _window(acct: dict, start: date | None, end: date | None) -> dict:
    txns = acct["transactions"]
    if start or end:
        kept = [t for t in txns if (start is None or t["posted_at"][:10] >= start.isoformat())
                and (end is None or t["posted_at"][:10] <= end.isoformat())]
    else:
        kept = txns
    first = txns.index(kept[0]) if kept else len(txns)
    if first == 0:
        opening = acct["opening_balance"]
    else:
        opening = txns[first - 1]["balance"]
    return {**{k: v for k, v in acct.items() if k not in ("transactions", "opening_balance", "period_start",
                                                            "period_end")},
            "period_start": (start.isoformat() if start else acct["period_start"]),
            "period_end": (end.isoformat() if end else acct["period_end"]),
            "opening_balance": f"{Decimal(opening):.2f}", "transactions": kept}


class DStatementSandbox:
    name = "dStatement"
    mode = "sandbox"

    def fetch_statement(self, tax_id: str, bank_code: str, account_no: str, start: date | None, end: date | None,
                        consent_token: str) -> SignedStatement:
        if not consent_token:
            raise ConsentMissing("dStatement requires the account holder's consent")
        s = sandbox_statement(tax_id, bank_code, account_no, start, end)
        s.signature = sign(s.statement)  # signed by the (sandbox) source bank
        return s


def get_statement_source() -> DStatementSandbox:
    if settings.connector_mode == "live":
        raise ConnectorError("live dStatement is not available; set FINSONA_CONNECTOR_MODE=sandbox")
    return DStatementSandbox()
