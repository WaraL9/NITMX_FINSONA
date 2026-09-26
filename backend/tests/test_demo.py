"""E16-01/02: instant demo reset and the persistent LLM cache."""

import json

from app import demo
from app.config import settings
from app.db import SessionLocal
from app.models import Case, LlmCache
from tests.helpers import RM


def _decision_count(client, case_id):
    return len(client.get(f"/api/cases/{case_id}/audit").json())


def test_reset_restores_seeded_state(client, seeded_case_id):
    client.post("/api/demo/reset")  # earlier tests in the session may have changed state
    before = _decision_count(client, seeded_case_id)
    items = client.get(f"/api/cases/{seeded_case_id}/watchlist").json()
    pending = next(i for i in items if i["status"] == "pending")
    r = client.post(f"/api/cases/{seeded_case_id}/watchlist/{pending['id']}/decision",
                    json={"action": "accept", "reason": "ทดสอบการรีเซ็ตเดโม"})
    assert r.status_code == 200
    assert _decision_count(client, seeded_case_id) > before

    r = client.post("/api/demo/reset")
    assert r.status_code == 200
    assert r.json()["mode"] == "snapshot"
    assert _decision_count(client, seeded_case_id) == before
    items = client.get(f"/api/cases/{seeded_case_id}/watchlist").json()
    assert next(i for i in items if i["id"] == pending["id"])["status"] == "pending"
    # encrypted files restored too: the statement PDF still opens
    doc = client.get(f"/api/cases/{seeded_case_id}/documents").json()[0]
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 200
    assert client.get("/api/audit/verify").json()["ok"]


def test_reset_is_ca_only(client):
    assert client.post("/api/demo/reset", headers=RM).status_code == 403


def test_reset_keeps_sla_clock_fresh(client, seeded_case_id):
    client.post("/api/demo/reset")
    with SessionLocal() as db:
        case = db.get(Case, seeded_case_id)
        from datetime import datetime, timezone
        age = datetime.now(timezone.utc) - case.submitted_at.replace(tzinfo=timezone.utc)
        assert abs(age - demo.SUBMITTED_AGO).total_seconds() < 60


def test_llm_cache_survives_reset(client):
    with SessionLocal() as db:
        db.merge(LlmCache(key="k" * 64, provider="anthropic", model="m", purpose="test", response={"a": 1}))
        db.commit()
    client.post("/api/demo/reset")  # exports before restoring, re-imports after
    with SessionLocal() as db:
        assert db.get(LlmCache, "k" * 64).response == {"a": 1}
    assert "k" * 64 in json.loads(settings.llm_cache_file.read_text(encoding="utf-8"))


def test_stale_snapshot_is_not_restored(monkeypatch):
    monkeypatch.setattr(demo, "fingerprint", lambda: "different")
    assert not demo.snapshot_valid()
