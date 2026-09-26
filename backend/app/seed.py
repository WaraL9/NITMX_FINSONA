"""Reset the database and seed demo data.

    python -m app.seed            # reset + seed the Kitti case
    python -m app.seed --keep     # seed without dropping existing data

Seeding builds the synthetic statement PDFs (E1-02) and uploads them through the real
ingest pipeline, so the demo data exercises the same parser a real upload does.
"""

import argparse

from app.db import Base, SessionLocal, create_all, engine
from app.models import Account, Case, Transaction, User
from app.scenario import load_scenario
from datetime import datetime, timedelta, timezone

from app.services import consent
from app.services.analysis import run_analysis
from app.services.ingest import ingest_document
from app.synth.build import build_case

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
            tax_id=sc.case.tax_id,
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
        db.flush()
        users = {u.role: u for u in db.query(User)}
        case.owner_user_id, case.rm_user_id = users["SME"].id, users["RM"].id
        # Submitted "yesterday" relative to seeding, so the 48h SLA countdown is live in the demo.
        case.submitted_at = datetime.now(timezone.utc) - timedelta(hours=20)
        case.contact_phone = "081-234-5678"
        consent.record(db, case.id, {p: True for p in consent.PURPOSES}, users["SME"].id)
        db.commit()
        for built in build_case("kitti"):
            ingest_document(db, case.id, built.path.read_bytes(), built.path.name, kind=built.kind,
                            password=built.password)
        run_analysis(db, case.id)
        return case.id


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--keep", action="store_true", help="do not drop existing data")
    args = p.parse_args()
    case_id = seed(reset=not args.keep)
    with SessionLocal() as db:
        n = db.query(Transaction).filter(Transaction.case_id == case_id).count()
    print(f"Seeded Kitti case id={case_id} with {n} transactions")
