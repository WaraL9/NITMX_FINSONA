import os
import tempfile

# Point the app at a throwaway DB before app modules are imported.
_tmp = tempfile.mkdtemp(prefix="finsona-test-")
os.environ["FINSONA_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["FINSONA_STORAGE_DIR"] = f"{_tmp}/storage"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402


@pytest.fixture()
def client():
    seed(reset=True)
    with TestClient(app) as c:
        yield c
