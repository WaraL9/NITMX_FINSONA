"""Statement coverage (E2-11): which days of the case period each account's statements cover.

A missing month silently understates revenue — and can hide exactly the month the
business would rather not show. Coverage comes from each statement's printed period
(a quiet period with no transactions is still covered); gaps are reported per account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Case, Document

Interval = tuple[date, date]


def merge(intervals: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1] + timedelta(days=1):
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def gaps(covered: list[Interval], start: date, end: date) -> list[Interval]:
    out: list[Interval] = []
    cursor = start
    for s, e in merge(covered):
        if e < cursor:
            continue
        if s > cursor:
            out.append((cursor, min(s - timedelta(days=1), end)))
        cursor = max(cursor, e + timedelta(days=1))
        if cursor > end:
            break
    if cursor <= end:
        out.append((cursor, end))
    return out


@dataclass
class AccountCoverage:
    account_id: int
    label: str
    owner_type: str
    covered: list[Interval]
    gaps: list[Interval]
    documents: int


def compute(db: Session, case: Case) -> dict:
    docs = list(db.scalars(select(Document).where(Document.case_id == case.id, Document.kind == "statement")))
    by_account: dict[int, list[Interval]] = {}
    counts: dict[int, int] = {}
    for d in docs:
        r = d.parse_report or {}
        if d.account_id is None or not r.get("period_start") or not r.get("period_end"):
            continue
        by_account.setdefault(d.account_id, []).append((date.fromisoformat(r["period_start"]),
                                                        date.fromisoformat(r["period_end"])))
        counts[d.account_id] = counts.get(d.account_id, 0) + 1
    all_iv = [iv for ivs in by_account.values() for iv in ivs]
    start = case.period_start or (min(s for s, _ in all_iv) if all_iv else None)
    end = case.period_end or (max(e for _, e in all_iv) if all_iv else None)
    accounts = []
    for a in db.scalars(select(Account).where(Account.case_id == case.id).order_by(Account.id)):
        ivs = merge(by_account.get(a.id, []))
        g = gaps(ivs, start, end) if start and end else []
        accounts.append(AccountCoverage(a.id, f"{a.bank_code} ·{a.account_no_masked[-6:-2]}", a.owner_type, ivs, g,
                                        counts.get(a.id, 0)))
    iso = lambda ivs: [[s.isoformat(), e.isoformat()] for s, e in ivs]  # noqa: E731
    return {
        "period_start": start.isoformat() if start else None,
        "period_end": end.isoformat() if end else None,
        "complete": all(not x.gaps for x in accounts),
        "accounts": [{"account_id": x.account_id, "label": x.label, "owner_type": x.owner_type,
                      "documents": x.documents, "covered": iso(x.covered), "gaps": iso(x.gaps),
                      "missing_days": sum((e - s).days + 1 for s, e in x.gaps)} for x in accounts],
    }
