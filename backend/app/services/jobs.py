"""Analysis as a background job with per-stage progress (E0-07).

POST starts a job and returns at once; the analysis runs after the response (FastAPI
BackgroundTasks) and the client polls the job. The job row is written when queued and
when finished. Stage progress in between lives in memory: the analysis holds SQLite's
write lock until it commits, so progress can't be written to the database meanwhile —
and reads of this in-memory state never touch that lock. This fits the single-process
server (`npm start`, `npm run dev`); several workers would need a shared queue (e.g. RQ).

At most one job per case runs at a time; starting another returns the running one.
Jobs left queued/running when the server stopped are marked failed on startup.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AnalysisJob
from app.services.analysis import AnalysisError, run_analysis

log = logging.getLogger("finsona.jobs")

# In run order. Engine stages (loops..aggregate) come from the engine's own timing laps.
STAGES = ("sync", "load", "loops", "classify", "tiers", "aggregate", "evidence", "save")
OPEN = ("queued", "running")

_live: dict[int, list[dict]] = {}
_lock = threading.Lock()


def _fresh_stages() -> list[dict]:
    return [{"key": k, "status": "pending", "ms": None} for k in STAGES]


def start(db: Session, case_id: int, user_id: int | None) -> tuple[AnalysisJob, bool]:
    """Returns (job, created). An open job for the case is returned instead of a new one."""
    with _lock:
        existing = db.scalar(select(AnalysisJob).where(AnalysisJob.case_id == case_id, AnalysisJob.status.in_(OPEN))
                             .order_by(AnalysisJob.id.desc()))
        if existing is not None:
            return existing, False
        job = AnalysisJob(case_id=case_id, status="queued", stages=_fresh_stages(), created_by=user_id)
        db.add(job)
        db.commit()
        db.refresh(job)
        _live[job.id] = _fresh_stages()
        return job, True


def run(job_id: int, user_id: int | None = None, ip: str | None = None) -> None:
    """Execute a queued job (called by BackgroundTasks, after the response is sent)."""
    stages = _live.setdefault(job_id, _fresh_stages())
    clock = time.perf_counter()
    stages[0]["status"] = "running"

    def progress(stage: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        i = STAGES.index(stage)
        stages[i].update(status="done", ms=round((now - clock) * 1000, 1))
        if i + 1 < len(stages):
            stages[i + 1]["status"] = "running"
        clock = now

    with SessionLocal() as db:
        job = db.get(AnalysisJob, job_id)
        if job is None or job.status != "queued":
            return
        job.status = "running"
        db.commit()
        case_id = job.case_id
    status, analysis_id, error = "succeeded", None, None
    try:
        with SessionLocal() as db:
            analysis_id = run_analysis(db, case_id, user_id=user_id, ip=ip, trigger="job", progress=progress).id
    except AnalysisError as e:
        status, error = "failed", str(e)
    except Exception:  # noqa: BLE001 — a job must always end in a final state
        log.exception("analysis job %s failed", job_id)
        status, error = "failed", "เกิดข้อผิดพลาดภายในระหว่างวิเคราะห์ — ดูบันทึกของเซิร์ฟเวอร์"
    for s in stages:
        if s["status"] == "running":
            s["status"] = "failed" if status == "failed" else "done"
    with SessionLocal() as db:
        job = db.get(AnalysisJob, job_id)
        if job is not None:  # gone if a demo reset restored the snapshot meanwhile
            job.status, job.analysis_id, job.error = status, analysis_id, error
            job.stages = [dict(s) for s in stages]
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
    _live.pop(job_id, None)


def snapshot(job: AnalysisJob) -> dict:
    """The job as the API returns it, with live stage progress while it runs."""
    live = _live.get(job.id)
    stages = [dict(s) for s in live] if live is not None and job.status in OPEN else job.stages
    return {"id": job.id, "case_id": job.case_id, "status": job.status, "stages": stages,
            "analysis_id": job.analysis_id, "error": job.error, "created_at": job.created_at,
            "finished_at": job.finished_at}


def recover(db: Session) -> int:
    """On startup: jobs that were queued/running when the server stopped can never finish."""
    stale = list(db.scalars(select(AnalysisJob).where(AnalysisJob.status.in_(OPEN))))
    for job in stale:
        job.status, job.error = "failed", "เซิร์ฟเวอร์เริ่มใหม่ระหว่างวิเคราะห์ — กดวิเคราะห์ใหม่อีกครั้ง"
        job.finished_at = datetime.now(timezone.utc)
    db.commit()
    return len(stale)
