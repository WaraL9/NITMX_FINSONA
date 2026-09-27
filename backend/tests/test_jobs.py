"""Analysis as a background job with per-stage progress (E0-07)."""

from app.db import SessionLocal
from app.models import AnalysisJob, AuditEntry, Case
from app.services import jobs
from app.services.analysis import run_analysis

STAGES = ["sync", "load", "loops", "classify", "tiers", "aggregate", "evidence", "save"]


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
    done = client.get(f"/api/cases/{seeded_case_id}/analysis/jobs/{job['id']}").json()
    assert done["status"] == "succeeded" and done["error"] is None and done["finished_at"]
    assert all(s["status"] == "done" and s["ms"] is not None for s in done["stages"])
    a = client.get(f"/api/cases/{seeded_case_id}/analysis").json()
    assert done["analysis_id"] == a["id"]
    assert a["waterfall"]["verified_operating_revenue"] == "25000000.00"  # canonical figure unchanged
    with SessionLocal() as db:
        entry = db.query(AuditEntry).filter_by(action="analysis_run").order_by(AuditEntry.id.desc()).first()
        assert entry.after["trigger"] == "job"


def test_one_open_job_per_case(client, seeded_case_id):
    with SessionLocal() as db:
        first, created = jobs.start(db, seeded_case_id, None)
        again, created_again = jobs.start(db, seeded_case_id, None)
    assert created and not created_again and again.id == first.id
    r = client.post(f"/api/cases/{seeded_case_id}/analysis/jobs")
    assert r.status_code == 200 and r.json()["id"] == first.id  # the running job, not a new one
    # Live progress comes from memory while the job is open.
    jobs._live[first.id][0].update(status="done", ms=12.5)
    jobs._live[first.id][1]["status"] = "running"
    live = client.get(f"/api/cases/{seeded_case_id}/analysis/jobs/{first.id}").json()
    assert live["stages"][0] == {"key": "sync", "status": "done", "ms": 12.5}
    assert live["stages"][1]["status"] == "running"
    jobs.run(first.id)
    assert client.get(f"/api/cases/{seeded_case_id}/analysis/jobs/{first.id}").json()["status"] == "succeeded"


def test_failed_job_says_why_and_marks_the_stage(client):
    case_id = client.post("/api/cases", json={"company_name": "ไม่มีเอกสาร", "industry": "ทดสอบ", "business_age_years": 1,
                                              "requested_amount": "100000", "purpose": "ทดสอบ", "tenor_months": 12,
                                              "annual_rate": "0.07"}).json()["id"]
    job = client.post(f"/api/cases/{case_id}/analysis/jobs").json()
    done = client.get(f"/api/cases/{case_id}/analysis/jobs/{job['id']}").json()
    assert done["status"] == "failed" and "upload statements first" in done["error"]
    by_key = {s["key"]: s["status"] for s in done["stages"]}
    assert by_key["sync"] == "done" and by_key["load"] == "failed" and by_key["save"] == "pending"


def test_jobs_cut_off_by_a_restart_are_failed_on_startup(seeded_case_id):
    with SessionLocal() as db:
        db.add(AnalysisJob(case_id=seeded_case_id, status="running", stages=[]))
        db.commit()
        assert jobs.recover(db) >= 1
        assert not db.query(AnalysisJob).filter(AnalysisJob.status.in_(("queued", "running"))).count()


def test_only_a_ca_starts_jobs_and_jobs_belong_to_their_case(client, seeded_case_id):
    from tests.helpers import RM
    assert client.post(f"/api/cases/{seeded_case_id}/analysis/jobs", headers=RM).status_code == 403
    with SessionLocal() as db:
        other = db.query(Case).filter(Case.id != seeded_case_id).first().id
        job_id = db.query(AnalysisJob).filter_by(case_id=seeded_case_id).first().id
    assert client.get(f"/api/cases/{other}/analysis/jobs/{job_id}").status_code == 404
