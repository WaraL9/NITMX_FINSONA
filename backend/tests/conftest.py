import os
import tempfile

# Point the app at a throwaway DB before app modules are imported.
_tmp = tempfile.mkdtemp(prefix="finsona-test-")
os.environ["FINSONA_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["FINSONA_STORAGE_DIR"] = f"{_tmp}/storage"
os.environ["FINSONA_SNAPSHOT_DIR"] = f"{_tmp}/snapshot"
os.environ["FINSONA_LLM_CACHE_FILE"] = f"{_tmp}/llm_cache.json"

import json  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402

GENERATED = settings.data_dir / "generated" / "kitti"


@pytest.fixture(scope="session")
def seeded_case_id() -> int:
    """Seed once per test session (builds the synthetic PDFs and ingests them)."""
    return seed(reset=True)


@pytest.fixture()
def client(seeded_case_id):
    """Test client logged in as the CA by default; pass headers= to act as someone else."""
    from tests.helpers import CA

    with TestClient(app, headers=CA) as c:
        yield c


@pytest.fixture(scope="session")
def truth(seeded_case_id) -> dict:
    return json.loads((GENERATED / "truth.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def statement_path(truth):
    def _path(account_key: str) -> Path:
        return GENERATED / truth["accounts"][account_key]["file"]

    return _path
