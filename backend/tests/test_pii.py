"""PII masking before LLM calls (E14-03) and the "what the AI saw" log (E14-04)."""

from app.ai import gateway
from app.ai.pii import mask, valid_thai_id
from app.db import SessionLocal
from app.models import LlmCall


def _with_checksum(first12: str) -> str:
    s = sum(int(d) * (13 - i) for i, d in enumerate(first12))
    return first12 + str((11 - s % 11) % 10)


def test_thai_id_needs_valid_checksum():
    good = _with_checksum("110170012345")
    bad = good[:-1] + str((int(good[-1]) + 1) % 10)
    assert valid_thai_id(good) and not valid_thai_id(bad)
    m = mask(f"บัตร {good[0]}-{good[1:5]}-{good[5:10]}-{good[10:12]}-{good[12]} และ {bad}")
    assert "[เลขประจำตัว]" in m.text and bad in m.text and m.counts == {"national_id": 1}


def test_contacts_accounts_and_people():
    text = ("โอนให้ นาย สมชาย ใจดี 081-234-5678 somchai@example.com บัญชี 123-4-56789-0 "
            "และ นาย สมชาย ใจดี อีกครั้ง, นางสาวอรอุมา พงษ์ไพร")
    m = mask(text)
    assert "สมชาย" not in m.text and "อรอุมา" not in m.text
    assert m.text.count("[บุคคล-1]") == 2 and "[บุคคล-2]" in m.text  # same person -> same token
    assert "[เบอร์โทร]" in m.text and "[อีเมล]" in m.text and "[เลขบัญชี]" in m.text


def test_business_data_is_left_alone():
    text = "บจก. สยามคลินิก กรุ๊ป xxx-x-x4521-x ยอด 1,200,000.00 บาท DSCR 1.05 เท่า เดือน 2026-03"
    m = mask(text)
    assert m.text == text and m.counts == {}


class Echo:
    provider, model = "fake", "fake-1"

    def __init__(self):
        self.seen = None

    def complete_json(self, system, user, schema, max_tokens):
        self.seen = user
        return {"ok": True}


def test_model_only_sees_masked_prompt_and_it_is_logged(seeded_case_id):
    echo = Echo()
    gateway.set_adapter(echo)
    try:
        with SessionLocal() as db:
            gateway.complete_json(db, "pii_test", "sys", "ลูกค้า นาย วิชัย มั่นคง โทร 0812345678", {"type": "object"},
                                  case_id=seeded_case_id)
            db.commit()
            call = db.query(LlmCall).filter(LlmCall.purpose == "pii_test").one()
        assert "วิชัย" not in echo.seen and "0812345678" not in echo.seen
        assert call.masked_prompt == echo.seen and call.outcome == "live"
        assert call.pii_counts == {"person_name": 1, "phone": 1}
    finally:
        gateway.set_adapter(None)


def test_unavailable_attempt_is_still_logged(client, seeded_case_id):
    client.post(f"/api/cases/{seeded_case_id}/memo/regenerate")
    calls = client.get(f"/api/cases/{seeded_case_id}/llm-calls").json()
    latest = calls[0]
    assert latest["purpose"] == "memo_narrative" and latest["outcome"] == "unavailable"
    assert "{{safe_limit}}" in latest["masked_prompt"]
