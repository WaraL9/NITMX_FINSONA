"""Build a scenario's synthetic documents on disk.

    python -m app.synth.build            # -> data/generated/kitti/

Writes one statement PDF per account plus `truth.json` (every row with its ground-truth
label and the band it was drawn in), which tests use to score the parser.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import settings
from app.scenario import load_scenario
from app.synth.generator import generate
from app.synth.statement_pdf import render_statement


@dataclass
class BuiltStatement:
    account_key: str
    path: Path
    password: str | None


def build_case(name: str = "kitti", out_dir: Path | None = None, seed: int = 42) -> list[BuiltStatement]:
    sc = load_scenario(name)
    out_dir = out_dir or settings.data_dir / "generated" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    gen = generate(sc, seed=seed)
    period = (sc.case.period_start, sc.case.period_end)

    built: list[BuiltStatement] = []
    truth: dict = {"scenario": name, "seed": seed, "accounts": {}}
    for key, acct in gen.accounts.items():
        pdf = out_dir / f"statement_{acct.spec.bank_code}_{key}.pdf"
        bands = render_statement(acct, period, pdf, password=acct.spec.pdf_password)
        truth["accounts"][key] = {
            "file": pdf.name,
            "bank_code": acct.spec.bank_code,
            "account_no_masked": acct.spec.account_no_masked,
            "opening_balance": f"{acct.opening_balance:.2f}",
            "rows": [dict(t.truth(), band=asdict(b)) for t, b in zip(acct.rows, bands, strict=True)],
        }
        built.append(BuiltStatement(key, pdf, acct.spec.pdf_password))

    (out_dir / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    return built


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("name", nargs="?", default="kitti")
    args = p.parse_args()
    for b in build_case(args.name):
        print(f"{b.account_key:10s} {b.path}{'  (password-protected)' if b.password else ''}")
