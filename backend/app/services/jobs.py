"""Analysis as a background job with per-stage progress (E0-07).

POST starts a job and returns at once; the analysis runs after the response (FastAPI
BackgroundTasks) in whichever server process received the request, and the client polls
the job from any process.

  * The job row is written when queued and when finished.
  * Stage progress in between goes to a small JSON file per job (`<storage>/jobs/<id>.json`),
    written atomically. Not the database: the analysis holds SQLite's write lock until it
    commits. A file is readable by every worker process, so several uvicorn workers can run.
  * The file carries a heartbeat, refreshed at every stage and every HEARTBEAT_S by a
    background thread (an LLM call can make one stage long). A job whose heartbeat is older
    than STALE_S has lost its process (crash, restart) and is marked failed — when polled,
    and on startup. Jobs of live workers are never touched.
  * At most one open job per case, enforced by a partial unique index, so it holds across
    processes; starting another returns the open one.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import AnalysisJob
from app.services.analysis import AnalysisError, run_analysis

log = logging.getLogger("finsona.jobs")

# In run order. Engine stages (loops..aggregate) come from the engine's own timing laps.
STAGES = ("sync", "load", "loops", "classify", "tiers", "aggregate", "evidence", "save")
OPEN = ("queued", "running")
HEARTBEAT_S = 5.0
STALE_S = 60.0


def _fresh_stages() -> list[dict]:
    return [{"key": k, "status": "pending", "ms": None} for k in STAGES]


# ---- progress file ------------------------------------------------------------------------

def _path(job_id: int) -> Path:
    return settings.storage_dir / "jobs" / f"{job_id}.json"


RETRIES = 5
_UNREADABLE = object()  # the file exists but another process holds it right now


def _write(job_id: int, stages: list[dict]) -> None:
    """Best effort: progress must never break the analysis. On Windows, replacing a file that
    another worker is reading is refused for a moment, so retry briefly and otherwise skip —
    the next stage or heartbeat writes again."""
    p = _path(job_id)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"stages": stages, "heartbeat": time.time()}), encoding="utf-8")
    except OSError:
        log.warning("job %s: could not write progress", job_id)
        return
    for attempt in range(RETRIES):
        try:
            os.replace(tmp, p)  # atomic: readers never see half a file
            return
        except PermissionError:
            time.sleep(0.02 * (attempt + 1))
        except OSError:
            break
    try:
        tmp.unlink()
    except OSError:
        pass


def _read(job_id: int):
    """The progress dict; None if there is no file; _UNREADABLE if it is momentarily locked."""
    for attempt in range(RETRIES):
        try:
            return json.loads(_path(job_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            time.sleep(0.02 * (attempt + 1))
    return _UNREADABLE


def _clear(job_id: int) -> None:
    try:
        _path(job_id).unlink()
    except OSError:
        pass


def _is_stale(job: AnalysisJob, now: float | None = None) -> bool:
    now = now or time.time()
    data = _read(job.id)
    if data is _UNREADABLE:
        return False  # someone is writing it: the job is alive
    if data is not None:
        return now - data["heartbeat"] > STALE_S
    created = job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=timezone.utc)
    return now - created.timestamp() > STALE_S  # queued but never picked up


# ---- lifecycle ----------------------------------------------------------------------------

def start(db: Session, case_id: int, user_id: int | None) -> tuple[AnalysisJob, bool]:
    """Returns (job, created). An open job for the case is returned instead of a new one."""
    existing = _open_job(db, case_id)
    if existing is not None and not _expire_if_stale(db, existing):
        return existing, False
    job = AnalysisJob(case_id=case_id, status="queued", stages=_fresh_stages(), created_by=user_id)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:  # another process started one for this case at the same moment
        db.rollback()
        return _open_job(db, case_id), False
    db.refresh(job)
    _write(job.id, _fresh_stages())
    return job, True


def _open_job(db: Session, case_id: int) -> AnalysisJob | None:
    return db.scalar(select(AnalysisJob).where(AnalysisJob.case_id == case_id, AnalysisJob.status.in_(OPEN))
                     .order_by(AnalysisJob.id.desc()))


def run(job_id: int, user_id: int | None = None, ip: str | None = None) -> None:
    """Execute a queued job (called by BackgroundTasks, after the response is sent)."""
    stages = _fresh_stages()
    stages[0]["status"] = "running"
    clock = time.perf_counter()
    lock = threading.Lock()

    def save() -> None:
        with lock:
            _write(job_id, stages)

    def progress(stage: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        i = STAGES.index(stage)
        with lock:
            stages[i].update(status="done", ms=round((now - clock) * 1000, 1))
            if i + 1 < len(stages):
                stages[i + 1]["status"] = "running"
        clock = now
        save()

    with SessionLocal() as db:
        job = db.get(AnalysisJob, job_id)
        if job is None or job.status != "queued":
            return
        job.status = "running"
        db.commit()
        case_id = job.case_id
    save()
    stop = threading.Event()

    def heartbeat() -> None:
        while not stop.wait(HEARTBEAT_S):
            save()

    beat = threading.Thread(target=heartbeat, name=f"job-{job_id}-heartbeat", daemon=True)
    beat.start()
    status, analysis_id, error = "succeeded", None, None
    try:
        with SessionLocal() as db:
            analysis_id = run_analysis(db, case_id, user_id=user_id, ip=ip, trigger="job", progress=progress).id
    except AnalysisError as e:
        status, error = "failed", str(e)
    except Exception:  # noqa: BLE001 — a job must always end in a final state
        log.exception("analysis job %s failed", job_id)
        status, error = "failed", "เกิดข้อผิดพลาดภายในระหว่างวิเคราะห์ — ดูบันทึกของเซิร์ฟเวอร์"
    finally:
        stop.set()
        beat.join()
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
    _clear(job_id)


def _expire_if_stale(db: Session, job: AnalysisJob) -> bool:
    """Mark an open job whose process stopped heart-beating as failed. Returns True if it did."""
    if job.status not in OPEN or not _is_stale(job):
        return False
    data = _read(job.id)
    job.stages = data["stages"] if isinstance(data, dict) else job.stages
    job.status = "failed"
    job.error = "กระบวนการวิเคราะห์หยุดทำงาน (เซิร์ฟเวอร์เริ่มใหม่หรือขัดข้อง) — กดวิเคราะห์ใหม่อีกครั้ง"
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    _clear(job.id)
    return True


def snapshot(db: Session, job: AnalysisJob) -> dict:
    """The job as the API returns it, with live stage progress while it runs."""
    _expire_if_stale(db, job)
    data = _read(job.id) if job.status in OPEN else None
    return {"id": job.id, "case_id": job.case_id, "status": job.status,
            "stages": data["stages"] if isinstance(data, dict) else job.stages,
            "analysis_id": job.analysis_id, "error": job.error, "created_at": job.created_at,
            "finished_at": job.finished_at}


def recover(db: Session) -> int:
    """On startup: fail open jobs whose process has stopped. Other live workers' jobs are left alone."""
    return sum(_expire_if_stale(db, j) for j in db.scalars(select(AnalysisJob).where(AnalysisJob.status.in_(OPEN))))
