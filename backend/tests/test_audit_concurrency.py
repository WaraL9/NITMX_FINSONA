"""The audit chain must not fork when requests append concurrently (E16-03 finding)."""

import threading

from app.db import SessionLocal
from app.services import audit


def test_concurrent_appends_keep_one_chain(seeded_case_id):
    barrier = threading.Barrier(8)
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            with SessionLocal() as db:
                barrier.wait()
                for j in range(5):
                    audit.log(db, "concurrency_test", case_id=seeded_case_id, target_id=f"{i}-{j}")
                    db.commit()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with SessionLocal() as db:
        status = audit.verify(db)
    assert status.ok, status
