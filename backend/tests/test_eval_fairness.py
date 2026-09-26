"""Evaluation harness (E15), fairness (E14-07) and protected attributes (E14-06)."""

import dataclasses

from app.engine import types as et
from app.eval.run import run
from app.models import Account, Case, Transaction

PROTECTED = {"gender", "sex", "religion", "ethnicity", "race", "nationality", "hometown", "birthplace",
             "age", "birth_date", "marital_status", "disability"}


def test_engine_has_no_protected_inputs():
    for cls in (et.EAccount, et.ETxn, et.EInvoice, et.EFiling, et.Policy):
        names = {f.name for f in dataclasses.fields(cls)}
        assert not names & PROTECTED, cls.__name__
    for model in (Case, Account, Transaction):
        assert not set(model.__table__.columns.keys()) & PROTECTED, model.__name__


def test_harness_on_small_bank():
    r = run(n_cases=4, n_extraction=1)
    e, x = r["engine"], r["extraction"]
    assert e["cases"] == 4 and e["tier_accuracy"] == 1.0 and e["waterfall_reconciles"] == 4
    assert e["loop_precision"] == 1.0 and e["loop_recall"] == 1.0 and e["loop_false_positive_rate"] == 0.0
    assert x["field_accuracy"] == 1.0 and x["bbox_on_row"] == 1.0 and x["row_count_mismatches"] == 0
    assert len({c["scale"] for c in r["cases"]}) > 1  # variants really differ


def test_no_size_bias_across_case_bank():
    # 4 cases is too few (existing debt is randomised); 20 seeded cases is stable.
    f = run(n_cases=20, n_extraction=0)["fairness"]
    assert f["coverage_ratio"] >= 0.8 and f["four_fifths_rule"] is True


def test_metrics_endpoint(client):
    m = client.get("/api/metrics")
    assert m.status_code == 200 and "engine" in m.json() and m.json()["generated_at"]
