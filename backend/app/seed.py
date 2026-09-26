"""Reset the database and seed demo data.

    python -m app.seed            # reset + seed the Kitti case
    python -m app.seed --keep     # seed without dropping existing data

I0 seeds users and the case header + accounts. Transactions, invoices, tax filings and
alt data are added by the synthetic generator in I1 (E1-02).
"""

import argparse

from app.db import Base, SessionLocal, create_all, engine
from app.models import Account, Case, User
from app.scenario import load_scenario

USERS = [
    ("คุณสมชาย (CA)", "CA"),
    ("คุณมานี (RM)", "RM"),
    ("คุณกิตติ (SME)", "SME"),
    ("คุณวิภา (Auditor)", "AUDITOR"),
]


def seed(reset: bool = True) -> int:
    if reset:
        Base.metadata.drop_all(engine)
    create_all()
    sc = load_scenario("kitti")
    with SessionLocal() as db:
        if not db.query(User).count():
            db.add_all(User(name=n, role=r) for n, r in USERS)
        case = Case(
            company_name=sc.case.company_name,
            industry=sc.case.industry,
            business_age_years=sc.case.business_age_years,
            requested_amount=sc.loan_request.amount,
            purpose=sc.case.purpose,
            tenor_months=sc.loan_request.tenor_months,
            annual_rate=sc.loan_request.annual_rate,
            status="in_review",
            source=sc.case.source,
            period_start=sc.case.period_start,
            period_end=sc.case.period_end,
            accounts=[
                Account(
                    bank_code=a.bank_code,
                    account_no_masked=a.account_no_masked,
                    account_name=a.account_name,
                    account_type=a.account_type,
                    owner_type=a.owner_type,
                )
                for a in sc.accounts
            ],
        )
        db.add(case)
        db.commit()
        return case.id


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--keep", action="store_true", help="do not drop existing data")
    args = p.parse_args()
    case_id = seed(reset=not args.keep)
    print(f"Seeded Kitti case id={case_id}")
