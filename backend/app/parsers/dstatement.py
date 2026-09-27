"""dStatement JSON -> ParsedStatement (E3-04).

The same normalized statement every PDF parser produces, so pulled statements go through
the same account matching, continuity checks and engine. Rows have no page or box: their
lineage is the signed bank record itself.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.core.money import to_money
from app.parsers.base import ParsedRow, ParsedStatement, ParseError

PARSER = "dstatement"
VERSION = "dstatement-v1"


def parse_dstatement(statement: dict) -> ParsedStatement:
    try:
        rows = []
        for i, t in enumerate(statement["transactions"]):
            cp = t.get("counterparty") or {}
            rows.append(ParsedRow(
                page_no=0, row_index=i, posted_at=datetime.fromisoformat(t["posted_at"]),
                code=t.get("code") or "", channel=t.get("channel") or "", description=t["description"],
                debit=to_money(t["debit"]), credit=to_money(t["credit"]), balance=to_money(t["balance"]),
                bbox=None, counterparty_name=cp.get("name"), counterparty_bank=cp.get("bank"),
                counterparty_account=cp.get("account"),
            ))
        return ParsedStatement(
            parser=PARSER, parser_version=VERSION, bank_code=statement["bank_code"],
            account_no=statement["account_no"], account_name=statement.get("account_name"),
            period_start=date.fromisoformat(statement["period_start"]),
            period_end=date.fromisoformat(statement["period_end"]),
            opening_balance=Decimal(statement["opening_balance"]), pages=[], rows=rows,
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as e:
        raise ParseError(f"malformed dStatement payload: {e}") from e
