"""Synthetic dStatement feed (E3-04): each account's statement as the source bank holds it.

Same transactions as the statement PDFs, as structured data. Counterparty fields are the
ones the bank prints in the transfer description, so a pulled statement and a parsed PDF
of the same account produce identical rows.
"""

from __future__ import annotations

from datetime import date

from app.parsers.synth_v1 import COUNTERPARTY_RE
from app.synth.generator import GeneratedCase


def make_feed(gen: GeneratedCase, period: tuple[date, date]) -> dict:
    accounts = []
    for acct in gen.accounts.values():
        spec = acct.spec
        txns = []
        for i, t in enumerate(acct.rows, 1):
            cp = COUNTERPARTY_RE.match(t.details)
            txns.append({
                "ref": f"{spec.bank_code}{t.at:%y%m%d}{i:05d}",
                "posted_at": t.at.isoformat(timespec="minutes"),
                "code": t.code,
                "channel": t.channel,
                "description": t.details,
                "debit": f"{t.debit:.2f}",
                "credit": f"{t.credit:.2f}",
                "balance": f"{t.balance:.2f}",
                "counterparty": ({"name": cp.group("name"), "bank": cp.group("bank"), "account": cp.group("acct")}
                                 if cp else None),
            })
        accounts.append({
            "bank_code": spec.bank_code,
            "account_no": spec.account_no_masked,
            "account_name": spec.account_name,
            "currency": "THB",
            "period_start": period[0].isoformat(),
            "period_end": period[1].isoformat(),
            "opening_balance": f"{acct.opening_balance:.2f}",
            "transactions": txns,
        })
    return {"tax_id": gen.scenario.case.tax_id, "accounts": accounts}
