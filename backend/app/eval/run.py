"""Evaluation harness (E15-02..04, E15-06, E14-07).

    python -m app.eval.run                     # 50 cases, extraction on 3, writes data/eval/results.json
    python -m app.eval.run --cases 10 --extraction 1

Measures, against generator ground truth:
  * extraction accuracy (E15-02): statement PDFs -> parser; field-level accuracy, character
    error rate (CER) of descriptions, and whether each bounding box lands on its row;
  * engine accuracy (E15-03): revenue-tier accuracy, loop detection precision / recall /
    false-positive rate at transaction level, waterfall reconciliation, cash-flow error;
  * performance (E15-04): parse throughput and engine time at ~1.2k and ~10k transactions;
  * time saved (E15-06): measured machine time vs ITMX's manual-effort assumptions;
  * fairness (E14-07): approval rates by business size (four-fifths rule).
Results are written with the date and git commit so every number on the metrics page is
traceable to a run.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import tempfile
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.config import REPO_DIR, settings
from app.engine import ratios
from app.engine.pipeline import analyze
from app.engine.types import EAccount, EFiling, EInvoice, ETxn, Policy
from app.eval.casebank import case_bank
from app.parsers.base import parse_statement
from app.synth.generator import generate
from app.synth.statement_pdf import render_statement
from app.synth.tax_docs import make_invoices, make_pp30

TIER_OF = {"revenue_t1_golden": "T1_golden", "revenue_t2_tax": "T2_tax",
           "revenue_t3_operational": "T3_operational", "unverified": "T4_unverified"}
# ITMX.md assumptions for the manual process, shown alongside measured numbers.
MANUAL_HOURS = (15, 20)
CA_REVIEW_MINUTES = (30, 45)


def _engine_inputs(gen, offset_acct: int = 0, offset_txn: int = 0):
    accts, txns, truth, key2id = [], [], {}, {}
    for i, (k, a) in enumerate(gen.accounts.items(), 1):
        key2id[k] = offset_acct + i
        accts.append(EAccount(offset_acct + i, a.spec.bank_code, a.spec.account_no_masked, a.spec.account_name,
                              a.spec.owner_type))
    n = offset_txn
    for k, a in gen.accounts.items():
        for t in a.rows:
            n += 1
            txns.append(ETxn(n, key2id[k], t.at, t.code, t.details, t.debit, t.credit, t.counterparty,
                             t.counterparty_account, t.counterparty_bank))
            truth[n] = t
    return accts, txns, truth


def _levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def eval_extraction(cases, n: int) -> dict:
    fields = Counter()
    total_fields = rows = pages = bbox_hits = 0
    cer_err = cer_len = 0
    seconds = 0.0
    with tempfile.TemporaryDirectory() as tmp:
        for name, sc, gseed, _ in cases[:n]:
            gen = generate(sc, seed=gseed)
            period = (sc.case.period_start, sc.case.period_end)
            for key, acct in gen.accounts.items():
                pdf = Path(tmp) / f"{name}_{key}.pdf"
                bands = render_statement(acct, period, pdf)  # unencrypted for the parser benchmark
                t0 = time.perf_counter()
                stmt = parse_statement(pdf)
                seconds += time.perf_counter() - t0
                pages += len(stmt.pages)
                for r, t, b in zip(stmt.rows, acct.rows, bands):
                    rows += 1
                    checks = {
                        "date": r.posted_at.date() == t.at.date(),
                        "time": r.posted_at.strftime("%H:%M") == t.at.strftime("%H:%M"),
                        "debit": r.debit == t.debit,
                        "credit": r.credit == t.credit,
                        "balance": r.balance == t.balance,
                        "code": r.code == t.code,
                    }
                    for k, ok in checks.items():
                        fields[k] += ok
                    total_fields += len(checks)
                    shown = t.details
                    cer_err += _levenshtein(r.description, shown) if r.description != shown else 0
                    cer_len += len(shown)
                    mid = (r.bbox.top + r.bbox.bottom) / 2
                    bbox_hits += r.page_no == b.page and b.top <= mid <= b.bottom
                if len(stmt.rows) != len(acct.rows):
                    fields["row_count_mismatch"] += 1
    correct = sum(v for k, v in fields.items() if k != "row_count_mismatch")
    return {
        "cases": min(n, len(cases)), "rows": rows, "pages": pages,
        "field_accuracy": round(correct / total_fields, 6) if total_fields else None,
        "per_field": {k: round(v / rows, 6) for k, v in fields.items() if k != "row_count_mismatch"},
        "description_cer": round(cer_err / cer_len, 6) if cer_len else None,
        "bbox_on_row": round(bbox_hits / rows, 6) if rows else None,
        "row_count_mismatches": fields["row_count_mismatch"],
        "parse_seconds": round(seconds, 2),
        "pages_per_second": round(pages / seconds, 1) if seconds else None,
        "rows_per_second": round(rows / seconds, 1) if seconds else None,
        "note": "Synthetic statement layout (FINSONA-SYNTH v1). Real-bank accuracy needs real statements (T-01).",
    }


def eval_engine(cases) -> tuple[dict, list[dict]]:
    tiers_ok = tiers_n = 0
    confusion: Counter[tuple[str, str]] = Counter()
    tp = fp = fn = tn = 0
    reconciles = cfo_exact = 0
    per_case = []
    times = []
    for name, sc, gseed, scale in cases:
        gen = generate(sc, seed=gseed)
        accts, txns, truth = _engine_inputs(gen)
        invs = [EInvoice(i, x.invoice_no, x.issue_date, x.buyer_name, x.total, x.subtotal)
                for i, x in enumerate(make_invoices(gen), 1)]
        fil = [EFiling(f.period, f.sales, f.output_vat) for f in make_pp30(gen)]
        t0 = time.perf_counter()
        r = analyze(accts, txns, invs, fil, sc.case.period_start, sc.case.period_end)
        times.append(time.perf_counter() - t0)
        for tid, t in truth.items():
            o = r.outcomes[tid]
            if t.category in TIER_OF:
                tiers_n += 1
                tiers_ok += o.tier == TIER_OF[t.category]
                confusion[(TIER_OF[t.category], o.tier or "none")] += 1
            is_loop, pred = t.loop_id is not None, o.loop_id is not None
            tp += is_loop and pred
            fp += (not is_loop) and pred
            fn += is_loop and not pred
            tn += (not is_loop) and not pred
        reconciles += r.reconciles
        truth_cfo = sum(sc.revenue.tiers.values(), Decimal("0")) - sc.costs.business_operating_6m
        cfo_exact += r.clean_cash_flow_period == truth_cfo
        cfo_m = r.clean_cash_flow_monthly
        s = ratios.size(sc.loan_request.amount, cfo_m, r.existing_debt_monthly, sc.loan_request.annual_rate,
                        sc.loan_request.tenor_months, Policy())
        per_case.append({"name": name, "scale": scale, "revenue_monthly": float(r.waterfall["verified_operating_revenue"] / 6),
                         "requested": float(sc.loan_request.amount), "safe_limit": float(s.safe_limit),
                         "passes_min_at_request": s.passes_min, "loops_true": len(sc.loops), "loops_found": len(r.loops),
                         "txns": len(txns)})
    n = len(cases)
    return {
        "cases": n,
        "transactions": sum(c["txns"] for c in per_case),
        "tier_accuracy": round(tiers_ok / tiers_n, 6),
        "tier_confusion": {f"{a}->{b}": v for (a, b), v in sorted(confusion.items()) if a != b},
        "loop_precision": round(tp / (tp + fp), 6) if tp + fp else None,
        "loop_recall": round(tp / (tp + fn), 6) if tp + fn else None,
        "loop_false_positive_rate": round(fp / (fp + tn), 6) if fp + tn else None,
        "loops_found_equals_true": sum(c["loops_true"] == c["loops_found"] for c in per_case),
        "waterfall_reconciles": reconciles,
        "cash_flow_exact": cfo_exact,
        "engine_ms_median": round(statistics.median(times) * 1000, 1),
    }, per_case


def eval_scale(cases, copies: int = 8) -> dict:
    """Engine time on one case vs `copies` businesses' worth of rows in one file."""
    name, sc, gseed, _ = cases[0]
    gen = generate(sc, seed=gseed)
    invs = [EInvoice(i, x.invoice_no, x.issue_date, x.buyer_name, x.total, x.subtotal)
            for i, x in enumerate(make_invoices(gen), 1)]
    fil = [EFiling(f.period, f.sales, f.output_vat) for f in make_pp30(gen)]
    out = {}
    for k in (1, copies):
        accts, txns = [], []
        for c in range(k):
            a, t, _ = _engine_inputs(gen, offset_acct=c * 100, offset_txn=c * 100_000)
            # Give each copy distinct account numbers so copies don't match each other's transfers.
            a = [replace(x, account_no=x.account_no.replace("-x", f"{c}-x", 1)) for x in a]
            accts += a
            txns += [replace(x, counterparty_account=(x.counterparty_account.replace("-x", f"{c}-x", 1)
                                                      if x.counterparty_account else None)) for x in t]
        t0 = time.perf_counter()
        analyze(accts, txns, invs, fil, sc.case.period_start, sc.case.period_end)
        out[f"{len(txns)}_txns_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


def fairness(per_case: list[dict]) -> dict:
    """E14-07: approval-at-request rate and safe-limit coverage by size (micro vs medium)."""
    median_rev = statistics.median(c["revenue_monthly"] for c in per_case)
    groups = {"micro": [c for c in per_case if c["revenue_monthly"] < median_rev],
              "medium": [c for c in per_case if c["revenue_monthly"] >= median_rev]}
    out = {}
    for g, cs in groups.items():
        out[g] = {"cases": len(cs),
                  "pass_rate_at_request": round(sum(c["passes_min_at_request"] for c in cs) / len(cs), 3) if cs else None,
                  "median_safe_limit_to_request": round(statistics.median(c["safe_limit"] / c["requested"] for c in cs), 3)
                  if cs else None}
    rates = [v["pass_rate_at_request"] for v in out.values() if v["pass_rate_at_request"] is not None]
    cov = [v["median_safe_limit_to_request"] for v in out.values() if v["median_safe_limit_to_request"]]
    out["split"] = f"median verified revenue {median_rev:,.0f} THB/month"
    out["pass_rate_ratio"] = round(min(rates) / max(rates), 3) if rates and max(rates) > 0 else None
    out["coverage_ratio"] = round(min(cov) / max(cov), 3) if len(cov) == 2 else None
    out["four_fifths_rule"] = (out["coverage_ratio"] or 0) >= 0.8
    out["inputs_used"] = "transactions, invoices, tax filings, utility payments only — no gender, religion, ethnicity, hometown or age"
    return out


def run(n_cases: int = 50, n_extraction: int = 3) -> dict:
    cases = case_bank(n_cases)
    started = time.perf_counter()
    extraction = eval_extraction(cases, n_extraction)
    engine, per_case = eval_engine(cases)
    scale = eval_scale(cases)
    pages_per_case = extraction["pages"] / max(extraction["cases"], 1)
    machine_s = pages_per_case / (extraction["pages_per_second"] or 1) + engine["engine_ms_median"] / 1000
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_DIR, capture_output=True,
                                text=True, timeout=10).stdout.strip() or None
    except Exception:
        commit = None
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": commit,
        "run_seconds": round(time.perf_counter() - started, 1),
        "extraction": extraction,
        "engine": engine,
        "performance": {**scale, "parse_seconds_per_case": round(pages_per_case / (extraction["pages_per_second"] or 1), 2)},
        "time_saved": {
            "machine_seconds_per_case": round(machine_s, 2),
            "manual_hours_assumed": list(MANUAL_HOURS),
            "ca_review_minutes_assumed": list(CA_REVIEW_MINUTES),
            "reduction_pct_assumed": [round(100 * (1 - (CA_REVIEW_MINUTES[1] / 60) / MANUAL_HOURS[0]), 1),
                                      round(100 * (1 - (CA_REVIEW_MINUTES[0] / 60) / MANUAL_HOURS[1]), 1)],
            "note": "Manual effort and CA review time are ITMX.md assumptions; machine time is measured.",
        },
        "fairness": fairness(per_case),
        "cases": per_case,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cases", type=int, default=50)
    p.add_argument("--extraction", type=int, default=3)
    args = p.parse_args()
    res = run(args.cases, args.extraction)
    out = settings.data_dir / "eval" / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    e, x = res["engine"], res["extraction"]
    print(f"wrote {out} in {res['run_seconds']}s")
    print(f"extraction: field acc {x['field_accuracy']}, CER {x['description_cer']}, bbox {x['bbox_on_row']}, "
          f"{x['pages_per_second']} pages/s")
    print(f"engine: tiers {e['tier_accuracy']}, loops P {e['loop_precision']} R {e['loop_recall']} "
          f"FPR {e['loop_false_positive_rate']}, reconcile {e['waterfall_reconciles']}/{e['cases']}, "
          f"CFO exact {e['cash_flow_exact']}/{e['cases']}")
    print(f"performance: {res['performance']}")
    print(f"fairness: {res['fairness']['pass_rate_ratio']=} {res['fairness']['coverage_ratio']=}")
