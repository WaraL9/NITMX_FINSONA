"""Build a scenario's synthetic documents on disk.

    python -m app.synth.build            # -> data/generated/kitti/

Writes one statement PDF per account, one ภ.พ.30 PDF per month, the PromptBiz sandbox
invoice feed (`promptbiz_invoices.json`), and `truth.json` (every row with its
ground-truth label and the band it was drawn in), which tests use to score the parser.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import settings
from app.scenario import Scenario, load_scenario
from app.synth.generator import generate
from app.synth.statement_pdf import render_statement
from app.synth.alt_data import make_alt_data
from app.synth.bills import write_bills
from app.synth.dstatement import make_feed
from app.synth.scan import scan_statement
from app.synth.etax_docs import make_etax_invoices, write_etax_files
from app.synth.generator import REVENUE_T2
from app.synth.tax_docs import make_invoices, make_pp30, render_pp30


@dataclass
class BuiltDoc:
    key: str  # account key for statements, YYYY-MM for ภ.พ.30
    kind: str  # statement | pp30
    path: Path
    password: str | None = None


def generated_dir(name: str = "kitti") -> Path:
    return settings.data_dir / "generated" / name


def build_case(name: str = "kitti", out_dir: Path | None = None, seed: int = 42,
               scenario: Scenario | None = None, scanned: frozenset[str] = frozenset()) -> list[BuiltDoc]:
    """`scanned` lists account keys whose statement is delivered as an image-only scan (E2-08)."""
    sc = scenario or load_scenario(name)
    out_dir = out_dir or generated_dir(name)
    out_dir.mkdir(parents=True, exist_ok=True)
    gen = generate(sc, seed=seed)
    period = (sc.case.period_start, sc.case.period_end)

    built: list[BuiltDoc] = []
    truth: dict = {"scenario": name, "seed": seed, "accounts": {}}
    for key, acct in gen.accounts.items():
        pdf = out_dir / f"statement_{acct.spec.bank_code}_{key}.pdf"
        bands = render_statement(acct, period, pdf, password=acct.spec.pdf_password)
        password = acct.spec.pdf_password
        if key in scanned:
            digital, pdf = pdf, out_dir / f"scan_{acct.spec.bank_code}_{key}.pdf"
            scan_statement(digital, pdf, settings.data_dir / "generated" / "ocr_recorded", password=password,
                           seed=seed + len(key))
            digital.unlink()
            password = None  # a photocopy has no PDF password
        truth["accounts"][key] = {
            "file": pdf.name,
            "bank_code": acct.spec.bank_code,
            "account_no_masked": acct.spec.account_no_masked,
            "opening_balance": f"{acct.opening_balance:.2f}",
            "rows": [dict(t.truth(), band=asdict(b)) for t, b in zip(acct.rows, bands, strict=True)],
        }
        built.append(BuiltDoc(key, "statement", pdf, password))

    invoices = make_invoices(gen)
    (out_dir / "promptbiz_invoices.json").write_text(
        json.dumps({"seller_tax_id": sc.case.tax_id, "invoices": [i.to_json() for i in invoices]},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    (out_dir / "dstatement.json").write_text(json.dumps(make_feed(gen, period), ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    (out_dir / "alt_data.json").write_text(
        json.dumps({"tax_id": sc.case.tax_id, "scenarios": make_alt_data(gen)}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    truth["pp30"] = {}
    for f in make_pp30(gen):
        pdf = out_dir / f"pp30_{f.period}.pdf"
        bands = render_pp30(f, sc.case.company_name, pdf)
        truth["pp30"][f.period] = {
            "file": pdf.name, "sales": f"{f.sales:.2f}", "output_vat": f"{f.output_vat:.2f}",
            "purchases": f"{f.purchases:.2f}", "input_vat": f"{f.input_vat:.2f}",
            "vat_payable": f"{f.vat_payable:.2f}", "bands": bands,
        }
        built.append(BuiltDoc(f.period, "pp30", pdf))

    # e-Tax invoice samples (E2-13) for the SME to upload; not ingested by the seed, so the
    # canonical figures are unchanged until someone uploads one.
    t2 = {k: sum(t.category == REVENUE_T2 for t in a.rows) for k, a in gen.accounts.items()}
    truth["etax"] = []
    if any(t2.values()):
        invoices = make_etax_invoices(gen, max(t2, key=t2.get))
        for inv in invoices:
            # The last one is also photographed, to show the OCR path for invoices.
            files = write_etax_files(inv, out_dir / "etax", settings.data_dir / "generated" / "ocr_recorded"
                                     if inv is invoices[-1] else None)
            truth["etax"].append({"invoice_no": inv.invoice_no, "issue_date": inv.issue_date.isoformat(),
                                  "buyer_name": inv.buyer_name, "subtotal": f"{inv.subtotal:.2f}",
                                  "vat": f"{inv.vat:.2f}", "total": f"{inv.total:.2f}",
                                  "account": inv.account_key, "paid_at": inv.paid_at,
                                  "paid_amount": f"{inv.paid_amount:.2f}", **files})

    # Utility / rent bills (E2-14) to upload; the photo's OCR response is recorded alongside the scans.
    truth["bills"] = write_bills(gen, out_dir / "bills", settings.data_dir / "generated" / "ocr_recorded")

    (out_dir / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    return built


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("name", nargs="?", default="kitti")
    args = p.parse_args()
    for b in build_case(args.name):
        print(f"{b.kind:9s} {b.key:10s} {b.path.name}{'  (password-protected)' if b.password else ''}")
