"""AI layer guarantees (E7) and the credit memo workflow (E11)."""

import hashlib
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.ai import gateway, narrative, tagging
from app.db import SessionLocal
from app.models import CreditMemo, LlmCache

CA, RM = {"X-User-Id": "1"}, {"X-User-Id": "2"}
FACTS = {"safe_limit": "3.50 ล้านบาท", "dscr_request": "1.05 เท่า"}


class FakeAdapter:
    provider, model = "fake", "fake-1"

    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def complete_json(self, system, user, schema, max_tokens):
        self.calls += 1
        return self.reply


@pytest.fixture()
def fake_llm():
    installed = []

    def install(reply):
        a = FakeAdapter(reply)
        gateway.set_adapter(a)
        installed.append(a)
        return a

    yield install
    gateway.set_adapter(None)
    with SessionLocal() as db:
        db.query(LlmCache).delete()
        db.commit()


# ---------- placeholder validator ----------

def test_fill_substitutes_engine_values():
    assert narrative.fill("วงเงินปลอดภัย {{safe_limit}}", FACTS) == "วงเงินปลอดภัย 3.50 ล้านบาท"


@pytest.mark.parametrize("draft", ["วงเงิน 3.5 ล้าน", "วงเงิน ๓ ล้าน", "DSCR {{dscr_request}} หรือ 1.1"])
def test_fill_rejects_model_written_numbers(draft):
    with pytest.raises(narrative.NarrativeInvalid):
        narrative.fill(draft, FACTS)


def test_fill_rejects_unknown_placeholder():
    with pytest.raises(narrative.NarrativeInvalid):
        narrative.fill("{{npl_forecast}}", FACTS)


# ---------- gateway + narrative ----------

def test_llm_draft_is_validated_filled_and_cached(fake_llm):
    a = fake_llm({"paragraphs": ["วงเงินที่ผ่อนไหวคือ {{safe_limit}}", "DSCR ตามคำขอ {{dscr_request}}"]})
    with SessionLocal() as db:
        n = narrative.draft(db, FACTS, {})
        assert n.source == "llm" and "3.50 ล้านบาท" in n.text and "{{" not in n.text
        again = narrative.draft(db, FACTS, {})
        assert again.source == "llm-cache" and a.calls == 1


def test_llm_numbers_fall_back_to_template(fake_llm):
    fake_llm({"paragraphs": ["วงเงินที่ผ่อนไหวคือ 3.9 ล้านบาท"]})  # model invented a number
    facts = {k: "x" for k in ["company", "requested", "accounts", "gross_inflow", "loops", "loop_count", "owner_inflow",
                              "unverified", "verified_revenue", "t1_share", "cfo_monthly", "existing_debt",
                              "dscr_request", "min_dscr", "target_dscr", "safe_limit"]}
    with SessionLocal() as db:
        n = narrative.draft(db, facts, {})
    assert n.source == "template" and "3.9" not in n.text


def test_no_live_llm_uses_template():
    gateway.set_adapter(None)
    assert gateway.status()["live"] is False
    with SessionLocal() as db:
        with pytest.raises(gateway.LLMUnavailable):
            gateway.complete_json(db, "t", "s", "u-unique", {"type": "object"})


def test_tagging_keeps_only_confident_cost_tags(fake_llm):
    fake_llm({"items": [
        {"id": 1, "tag": "rent", "confidence": 0.9, "rationale": "ค่าเช่า"},
        {"id": 2, "tag": "payroll", "confidence": 0.4, "rationale": "ไม่แน่ใจ"},
        {"id": 3, "tag": "rent", "confidence": 0.95, "rationale": "ไม่ได้ส่งไป"},
    ]})
    with SessionLocal() as db:
        got = tagging.suggest(db, [(1, "โอนให้เจ้าของโกดัง", None), (2, "โอน", None)])
    assert [(s.txn_id, s.tag) for s in got] == [(1, "rent")]


# ---------- analysis extras over the API ----------

def test_analysis_has_evidence_and_drivers(client, seeded_case_id):
    a = client.get(f"/api/cases/{seeded_case_id}/analysis").json()
    assert a["alt_data"]["liveness_confirmed"] and a["alt_data"]["haircut"] == "0"
    assert a["cash_pattern"]["detected"] and a["cash_pattern"]["top_weekdays"] == ["จันทร์", "พฤหัสบดี"]
    keys = {d["key"] for d in a["drivers"]}
    assert {"T1_golden", "existing_debt", "unverified", "household"} <= keys
    s = client.get(f"/api/cases/{seeded_case_id}/sizing").json()
    assert s["structure"] == {"needed": True, "term_loan": "3500000.00", "trade_line": "1000000.00",
                              "total": "4500000.00", "shortfall": "1500000.00", "trade_line_ratio": "0.40"}


def test_stress_params(client, seeded_case_id):
    base = client.get(f"/api/cases/{seeded_case_id}/sizing", params={"amount": "3500000"}).json()
    hit = client.get(f"/api/cases/{seeded_case_id}/sizing",
                     params={"amount": "3500000", "revenue_drop": "0.05", "rate_rise_bp": 100}).json()
    assert hit["stressed"] and D(hit["dscr"]) < D(base["dscr"]) and D(hit["safe_limit"]) < D(base["safe_limit"])
    assert client.get(f"/api/cases/{seeded_case_id}/sizing", params={"revenue_drop": "2"}).status_code == 422


def test_alt_scenario_switch_applies_haircut(client, seeded_case_id):
    url = f"/api/cases/{seeded_case_id}/sandbox/alt-scenario"
    try:
        a = client.put(url, json={"scenario": "late_electricity_twice"}, headers=CA).json()
        assert a["alt_data"]["haircut"] == "0.10" and a["alt_data"]["late_30"] == 2
        assert any(d["key"] == "alt_data" for d in a["drivers"])
        assert client.get(f"/api/cases/{seeded_case_id}/sizing").json()["safe_limit"] == "2970000.00"
    finally:
        client.put(url, json={"scenario": "clean"}, headers=CA)
    assert client.get(f"/api/cases/{seeded_case_id}/sizing").json()["safe_limit"] == "3500000.00"


# ---------- memo ----------

@pytest.fixture()
def draft_memo(client, seeded_case_id):
    with SessionLocal() as db:
        m = db.query(CreditMemo).filter(CreditMemo.case_id == seeded_case_id).first()
        if m and m.status == "signed":
            client.post(f"/api/cases/{seeded_case_id}/memo/reopen", json={"reason": "เปิดใหม่เพื่อทดสอบ"}, headers=CA)
    yield
    client.post(f"/api/cases/{seeded_case_id}/memo/reopen", json={"reason": "คืนสถานะหลังการทดสอบ"}, headers=CA)


def test_memo_package_and_template_narrative(client, seeded_case_id, draft_memo):
    p = client.get(f"/api/cases/{seeded_case_id}/memo").json()
    assert p["memo"]["status"] == "draft" and p["memo"]["narrative_source"] == "template"
    assert "3.50 ล้านบาท" in p["memo"]["narrative"] and "{{" not in p["memo"]["narrative"]
    assert p["sizing_safe"]["amount"] == "3500000.00" and p["sizing_request"]["structure"]["trade_line"] == "1000000.00"


def test_sign_rules_pdf_and_audit(client, seeded_case_id, draft_memo):
    url = f"/api/cases/{seeded_case_id}/memo/sign"
    body = {"recommendation": "approve_structured", "approved_amount": "3500000", "trade_line_amount": "1000000",
            "reason": "กระแสเงินสดจริงรองรับได้ที่วงเงินปลอดภัย พร้อม Trade Line ผูก PromptBiz"}
    assert client.post(url, json=body, headers=RM).status_code == 403
    bad = {**body, "recommendation": "approve"}  # 'approve' must equal the request
    assert client.post(url, json=bad, headers=CA).status_code == 422

    p = client.post(url, json=body, headers=CA).json()
    m = p["memo"]
    assert m["status"] == "signed" and p["case"]["status"] == "decided" and m["signed_by"].startswith("คุณสมชาย")
    pdf = client.get(f"/api/cases/{seeded_case_id}/memo/pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    assert hashlib.sha256(pdf.content).hexdigest() == m["pdf_sha256"]
    signed = next(e for e in client.get(f"/api/cases/{seeded_case_id}/audit").json() if e["action"] == "memo_signed")
    assert signed["after"]["pdf_sha256"] == m["pdf_sha256"] and signed["after"]["audit_head_in_pdf"] == m["audit_head"]
    assert client.post(url, json=body, headers=CA).status_code == 409  # already signed
    assert client.get("/api/audit/verify").json()["ok"]


def test_ca_can_edit_narrative(client, seeded_case_id, draft_memo):
    text = "สรุปโดยเจ้าหน้าที่: ธุรกิจมีกระแสเงินสดจริงและยืนยันรายได้ด้วยใบแจ้งหนี้อิเล็กทรอนิกส์"
    p = client.put(f"/api/cases/{seeded_case_id}/memo/narrative", json={"narrative": text}, headers=CA).json()
    assert p["memo"]["narrative"] == text and p["memo"]["narrative_source"] == "ca_edited"
    # Regenerate returns to a system draft.
    p = client.post(f"/api/cases/{seeded_case_id}/memo/regenerate").json()
    assert p["memo"]["narrative_source"] == "template"
