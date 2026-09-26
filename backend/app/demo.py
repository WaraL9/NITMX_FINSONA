"""Demo hardening (E16-01/02): instant reset and an LLM cache that survives reseeding.

Seeding parses every statement PDF for real (~5 s). A reset during a pitch must be
instant, so after each seed the database and encrypted file store are snapshotted;
a reset restores that snapshot with SQLite's online backup API (safe while the API
server holds open connections). The snapshot carries a fingerprint of the schema,
engine and scenario, so a stale snapshot is never restored — it falls back to a full
reseed instead.

LLM responses are exported to ``data/llm_cache.json`` (masked prompts only — no PII)
and re-imported on every seed, so a narrative generated once online replays offline.
"""

import hashlib
import json
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, settings
from app.db import SessionLocal, engine
from app.engine.types import ENGINE_VERSION
from app.models import Case, LlmCache

SUBMITTED_AGO = timedelta(hours=20)  # keeps the 48h SLA countdown live after every reset


# ---------------------------------------------------------------- LLM cache file

def export_llm_cache(db: Session) -> int:
    """Merge the DB's cached responses into the cache file. Returns the file's entry count."""
    path = settings.llm_cache_file
    if path is None:
        return 0
    entries = _read_cache_file(path)
    for row in db.scalars(select(LlmCache)):
        entries[row.key] = {"provider": row.provider, "model": row.model, "purpose": row.purpose,
                            "response": row.response}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(entries.items())), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return len(entries)


def import_llm_cache(db: Session) -> int:
    path = settings.llm_cache_file
    if path is None:
        return 0
    entries = _read_cache_file(path)
    for key, e in entries.items():
        db.merge(LlmCache(key=key, provider=e["provider"], model=e["model"], purpose=e["purpose"],
                          response=e["response"]))
    db.commit()
    return len(entries)


def _read_cache_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- snapshot / reset

def _db_path() -> Path:
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        raise RuntimeError("demo snapshots need a file-backed SQLite database")
    return Path(url.removeprefix("sqlite:///"))


def fingerprint() -> str:
    """Changes whenever a snapshot could no longer reproduce a fresh seed."""
    h = hashlib.sha256(ENGINE_VERSION.encode())
    app_dir = BACKEND_DIR / "app"
    for p in [app_dir / "models.py", app_dir / "seed.py", *sorted((settings.data_dir).glob("scenario_*.yaml"))]:
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _raw(conn) -> sqlite3.Connection:
    return conn.driver_connection  # type: ignore[no-any-return]


def take_snapshot() -> None:
    snap = settings.snapshot_dir
    if snap.exists():
        shutil.rmtree(snap)
    snap.mkdir(parents=True)
    raw = engine.raw_connection()
    try:
        dest = sqlite3.connect(snap / "db.sqlite")
        _raw(raw).backup(dest)
        dest.close()
    finally:
        raw.close()
    if settings.storage_dir.exists():
        shutil.copytree(settings.storage_dir, snap / "storage")
    (snap / "meta.json").write_text(json.dumps({"fingerprint": fingerprint(), "db": str(_db_path()),
                                                "storage": str(settings.storage_dir),
                                                "taken_at": datetime.now(timezone.utc).isoformat()}))


def snapshot_valid() -> bool:
    try:
        meta = json.loads((settings.snapshot_dir / "meta.json").read_text())
    except (OSError, ValueError):
        return False
    # Paths are stored absolute in the DB, so a snapshot is only valid for the same locations.
    return (meta.get("fingerprint") == fingerprint() and meta.get("storage") == str(settings.storage_dir)
            and (settings.snapshot_dir / "db.sqlite").exists())


def _refresh_clock() -> None:
    with SessionLocal() as db:
        for case in db.scalars(select(Case).where(Case.submitted_at.is_not(None))):
            case.submitted_at = datetime.now(timezone.utc) - SUBMITTED_AGO
        db.commit()


def reset() -> dict:
    """Restore the freshly-seeded demo state. Returns {"mode", "ms"}."""
    t0 = time.perf_counter()
    if snapshot_valid():
        # Keep responses generated since the last seed before they are overwritten.
        with SessionLocal() as db:
            export_llm_cache(db)
        src = sqlite3.connect(settings.snapshot_dir / "db.sqlite")
        raw = engine.raw_connection()
        try:
            src.backup(_raw(raw))
        finally:
            raw.close()
            src.close()
        if settings.storage_dir.exists():
            shutil.rmtree(settings.storage_dir)
        if (settings.snapshot_dir / "storage").exists():
            shutil.copytree(settings.snapshot_dir / "storage", settings.storage_dir)
        with SessionLocal() as db:
            import_llm_cache(db)
        _refresh_clock()
        mode = "snapshot"
    else:
        from app.seed import seed

        seed(reset=True)
        mode = "reseed"
    return {"mode": mode, "ms": round((time.perf_counter() - t0) * 1000)}
