"""Analysis as a background job with per-stage progress (E0-07), safe across server processes."""

import json
import time

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import AnalysisJob, AuditEntry, Case
from app.services import jobs
from app.services.analysis import run_analysis

STAGES = ["sync", "load", "loops", "classify", "tiers", "aggregate", "evidence", "save"]


def _job(client, case_id, job_id):
    return client.get(f"/api/cases/{case_id}/analysis/jobs/{job_id}").json()


def _age_heartbeat(job_id: int, seconds: float) -> None:
    p = jobs._path(job_id)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["heartbeat"] -= seconds
    p.write_text(json.dumps(data), encoding="utf-8")


def test_progress_reports_every_stage_in_order(seeded_case_id):
    seen = []
    with SessionLocal() as db:
        run_analysis(db, seeded_case_id, progress=seen.append)
    assert seen == STAGES


def test_job_runs_in_the_background_and_reports_stages(client, seeded_case_id):
    r = client.post(f"/api/cases/{seeded_case_id}/analysis/jobs")
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "queued" and [s["key"] for s in job["stages"]] == STAGES
    # The test client finishes background tasks before returning; a browser polls instead.
    done = _job(client, seeded_case_id, job["id"])
    assert done["status"] == "succeeded" and done["error"] is None and done["finished_at"]
    assert all(s["status"] == "done" and s["ms"] is not None for s in done["stages"])
    assert not jobs._path(job["id"]).exists()  # progress file removed once the row holds the result
    a = client.get(f"/api/cases/{seeded_case_id}/analysis").json()
    assert done["analysis_id"] == a["id"]
    assert a["waterfall"]["verified_operating_revenue"] == "25000000.00"  # canonical figure unchanged
    with SessionLocal() as db:
        entry = db.query(AuditEntry).filter_by(action="analysis_run").order_by(AuditEntry.id.desc()).first()
        assert entry.after["trigger"] == "job"


def test_one_open_job_per_case_and_progress_from_any_process(client, seeded_case_id):
    with SessionLocal() as db:
        first, created = jobs.start(db, seeded_case_id, None)
        again, created_again = jobs.start(db, seeded_case_id, None)
    assert created and not created_again and again.id == first.id
    r = client.post(f"/api/cases/{seeded_case_id}/analysis/jobs")
    assert r.status_code == 200 and r.json()["id"] == first.id  # the open job, not a new one
    # The database refuses a second open job for the case, whichever process tries.
    with SessionLocal() as db, pytest.raises(IntegrityError):
        db.add(AnalysisJob(case_id=seeded_case_id, status="running", stages=[]))
        db.commit()
    # Progress lives in a file, not in this process's memory: whatever the file says is served.
    stages = jobs._fresh_stages()
    stages[0].update(status="done", ms=12.5)
    stages[1]["status"] = "running"
    jobs._write(first.id, stages)
    live = _job(client, seeded_case_id, first.id)
    assert live["stages"][0] == {"key": "sync", "status": "done", "ms": 12.5}
    assert live["stages"][1]["status"] == "running"
    jobs.run(first.id)
    assert _job(client, seeded_case_id, first.id)["status"] == "succeeded"


def test_heartbeat_keeps_a_long_stage_alive(seeded_case_id, monkeypatch):
    writes = []
    real_write = jobs._write
    monkeypatch.setattr(jobs, "HEARTBEAT_S", 0.05)
    monkeypatch.setattr(jobs, "_write", lambda job_id, stages: (writes.append(time.time()), real_write(job_id, stages)))
    real_run = jobs.run_analysis

    def slow(db, case_id, **kw):
        time.sleep(0.4)  # e.g. waiting on an LLM
        return real_run(db, case_id, **kw)

    monkeypatch.setattr(jobs, "run_analysis", slow)
    with SessionLocal() as db:
        job, _ = jobs.start(db, seeded_case_id, None)
    jobs.run(job.id)
    heartbeats = [t for t in writes if t < writes[0] + 0.4]
    assert len(heartbeats) >= 4  # refreshed while nothing else was written


def test_stale_job_is_failed_but_a_live_one_is_left_alone(client, seeded_case_id):
    with SessionLocal() as db:
        job, _ = jobs.start(db, seeded_case_id, None)
        assert jobs.recover(db) == 0  # fresh heartbeat: another worker may be running it
    _age_heartbeat(job.id, jobs.STALE_S + 5)
    done = _job(client, seeded_case_id, job.id)  # polling notices the dead process
    assert done["status"] == "failed" and "หยุดทำงาน" in done["error"]
    assert not jobs._path(job.id).exists()
    with SessionLocal() as db:  # the case can run again
        again, created = jobs.start(db, seeded_case_id, None)
        assert created
        _age_heartbeat(again.id, jobs.STALE_S + 5)
        assert jobs.recover(db) == 1  # startup sweep


def test_failed_job_says_why_and_marks_the_stage(client):
    case_id = client.post("/api/cases", json={"company_name": "ไม่มีเอกสาร", "industry": "ทดสอบ", "business_age_years": 1,
                                              "requested_amount": "100000", "purpose": "ทดสอบ", "tenor_months": 12,
                                              "annual_rate": "0.07"}).json()["id"]
    job = client.post(f"/api/cases/{case_id}/analysis/jobs").json()
    done = _job(client, case_id, job["id"])
    assert done["status"] == "failed" and "upload statements first" in done["error"]
    by_key = {s["key"]: s["status"] for s in done["stages"]}
    assert by_key["sync"] == "done" and by_key["load"] == "failed" and by_key["save"] == "pending"


def test_job_whose_row_vanished_still_finishes_cleanly(seeded_case_id, monkeypatch):
    """A demo reset can restore the snapshot while a job runs; the job must not crash at the end."""
    with SessionLocal() as db:
        job, _ = jobs.start(db, seeded_case_id, None)
    real_run = jobs.run_analysis

    def run_then_drop_row(db, case_id, **kw):
        a = real_run(db, case_id, **kw)
        with SessionLocal() as other:
            other.delete(other.get(AnalysisJob, job.id))
            other.commit()
        return a

    monkeypatch.setattr(jobs, "run_analysis", run_then_drop_row)
    jobs.run(job.id)
    assert not jobs._path(job.id).exists()


def test_only_a_ca_starts_jobs_and_jobs_belong_to_their_case(client, seeded_case_id):
    from tests.helpers import RM
    assert client.post(f"/api/cases/{seeded_case_id}/analysis/jobs", headers=RM).status_code == 403
    with SessionLocal() as db:
        other = db.query(Case).filter(Case.id != seeded_case_id).first().id
        job_id = db.query(AnalysisJob).filter_by(case_id=seeded_case_id).first().id
    assert client.get(f"/api/cases/{other}/analysis/jobs/{job_id}").status_code == 404


def test_progress_file_locked_by_another_process_never_fails_the_job(client, seeded_case_id, monkeypatch):
    """Windows refuses to replace a file another worker is reading; progress is best effort."""
    def refused(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(jobs.os, "replace", refused)
    job = client.post(f"/api/cases/{seeded_case_id}/analysis/jobs").json()
    monkeypatch.undo()
    done = _job(client, seeded_case_id, job["id"])
    assert done["status"] == "succeeded", done["error"]
    assert not list(jobs._path(job["id"]).parent.glob(f"{job['id']}.*.tmp"))  # no temp files left behind
