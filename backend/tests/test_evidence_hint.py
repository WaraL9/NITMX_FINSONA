"""Watchlist evidence hints (E7-05): what would verify each item, never a number from the LLM."""

import re
from datetime import datetime
from decimal import Decimal

import pytest

from app.ai import gateway
from app.ai.evidence_hint import HintInput, suggest, template
from app.db import SessionLocal
from app.models import LlmCache, LlmCall, WatchlistItem
from app.services.analysis import run_analysis

CASH = HintInput(1, "ฝากเงินสด", None, "CD", Decimal("700000.00"), datetime(2026, 5, 27, 10, 12),
                 "ฝากเงินสดก้อนใหญ่ ไม่มีเอกสารการค้ารองรับ")
PERSON = HintInput(2, "รับโอนจาก นางสาวพิมพ์ชนก ใจดี", "นางสาวพิมพ์ชนก ใจดี", "TR-IN", Decimal("850000.00"),
                   datetime(2026, 2, 19, 14, 0), "ไม่มีใบแจ้งหนี้ PromptBiz หรือยอดใน ภ.พ.30 รองรับ · โอนจากบุคคลธรรมดา")


class FakeAdapter:
    """Answers with a fixed reply per item id found in the prompt."""

    provider = "fake"

    def __init__(self, model: str, per_item):
        self.model, self.per_item, self.prompts = model, per_item, []

    def complete_json(self, system, user, schema, max_tokens):
        self.prompts.append(user)
        return {"items": [{"id": int(i), **self.per_item(int(i))} for i in re.findall(r"id=(\d+)", user)]}


@pytest.fixture()
def llm():
    def install(model, per_item):
        a = FakeAdapter(model, per_item)
        gateway.set_adapter(a)
        return a

    yield install
    gateway.set_adapter(None)
    with SessionLocal() as db:
        db.query(LlmCache).delete()
        db.commit()


def test_template_fits_the_kind_of_inflow():
    cash, person = template(CASH), template(PERSON)
    assert cash.source == person.source == "template"
    assert "เงินสด" in cash.evidence[0]["document"] and "700,000.00 บาท" in cash.evidence[0]["document"]
    assert "27/05/2569" in cash.question
    assert "นางสาวพิมพ์ชนก ใจดี" in person.evidence[0]["document"] and len(person.evidence) == 3


def test_llm_hint_gets_engine_numbers(seeded_case_id, llm):
    llm("hint-ok", lambda i: {
        "evidence": [{"document": "สัญญาว่าจ้างงานตกแต่งคลินิกงวดแรก ยอด {{amount}}",
                      "why": "ยอดตรงกับงวดแรกของสัญญา และไม่อยู่ในยอดขาย ภ.พ.30"}],
        "question": "ยอด {{amount}} จาก {{counterparty}} วันที่ {{date}} เป็นงวดใดของสัญญา"})
    with SessionLocal() as db:
        hints = suggest(db, [PERSON], "รับเหมาตกแต่งภายใน")
    h = hints[PERSON.item_id]
    assert h.source == "live" and h.model == "hint-ok"
    assert h.evidence[0]["document"] == "สัญญาว่าจ้างงานตกแต่งคลินิกงวดแรก ยอด 850,000.00 บาท"
    assert "ภ.พ.30" in h.evidence[0]["why"]  # the form's name is allowed
    assert h.question == "ยอด 850,000.00 บาท จาก นางสาวพิมพ์ชนก ใจดี วันที่ 19/02/2569 เป็นงวดใดของสัญญา"


def test_llm_digits_or_unknown_placeholders_fall_back_to_template(seeded_case_id, llm):
    bad = {1: {"evidence": [{"document": "ใบเสร็จ 700,000 บาท", "why": "x"}], "question": "?"},  # wrote a number
           2: {"evidence": [{"document": "สัญญา {{contract_value}}", "why": "x"}], "question": "?"}}  # invented placeholder
    llm("hint-bad", lambda i: bad[i])
    with SessionLocal() as db:
        hints = suggest(db, [CASH, PERSON], "รับเหมาตกแต่งภายใน")
    assert hints[1].source == hints[2].source == "template"
    assert hints[1].evidence == template(CASH).evidence


def test_no_llm_means_template_and_the_attempt_is_logged(seeded_case_id):
    gateway.set_adapter(None)
    with SessionLocal() as db:
        before = db.query(LlmCall).filter_by(purpose="watchlist_evidence_hint").count()
        hints = suggest(db, [CASH], "ร้านค้า")
        db.commit()
        after = db.query(LlmCall).filter_by(purpose="watchlist_evidence_hint").count()
    assert hints[1].source == "template" and after == before + 1


def test_seeded_watchlist_has_hints_and_llm_never_moves_a_figure(client, seeded_case_id, llm):
    items = client.get(f"/api/cases/{seeded_case_id}/watchlist").json()
    assert items and all(i["evidence_hint"]["source"] == "template" for i in items if i["status"] == "pending")
    cash = next(i for i in items if "ฝากเงินสด" in i["transaction"]["description"])
    assert "เงินสด" in cash["evidence_hint"]["evidence"][0]["document"]

    before = client.get(f"/api/cases/{seeded_case_id}/analysis").json()
    fake = llm("hint-case", lambda i: {"evidence": [{"document": "ใบส่งของและใบเสร็จของยอด {{amount}}",
                                                     "why": "พิสูจน์ที่มาของเงิน"}],
                                       "question": "ยอด {{amount}} วันที่ {{date}} มาจากลูกค้ารายใด"})
    try:
        with SessionLocal() as db:
            run_analysis(db, seeded_case_id, sync_invoices=False)
        after = client.get(f"/api/cases/{seeded_case_id}/analysis").json()
        assert after["waterfall"] == before["waterfall"] and after["tiers"] == before["tiers"]
        items = client.get(f"/api/cases/{seeded_case_id}/watchlist").json()
        live = [i for i in items if i["status"] in ("pending", "queried")]
        assert live and all(i["evidence_hint"]["source"] == "live" for i in live)
        assert all(f"{Decimal(i['transaction']['credit']):,.2f} บาท" in i["evidence_hint"]["question"] for i in live)
        # Business context reaches the model; masked text is what was sent.
        assert "ประเภทธุรกิจของผู้กู้" in fake.prompts[0]
    finally:
        gateway.set_adapter(None)
        with SessionLocal() as db:  # back to template hints for the other tests
            for w in db.query(WatchlistItem).filter_by(case_id=seeded_case_id):
                w.evidence_hint = None
            db.commit()
            run_analysis(db, seeded_case_id, sync_invoices=False)
