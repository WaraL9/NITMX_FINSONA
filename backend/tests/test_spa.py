"""E16-05: the API serves the built SPA without shadowing API routes or leaking files."""

import pytest

from app.config import settings

pytestmark = pytest.mark.skipif(not (settings.frontend_dist / "index.html").exists(),
                                reason="frontend not built (npm run build)")


def test_deep_links_get_the_app(client):
    for path in ("/", "/cases/1", "/rm"):
        r = client.get(path)
        assert r.status_code == 200 and r.text.lstrip().lower().startswith("<!doctype html>")


def test_unknown_api_paths_stay_json_404(client):
    for path in ("/api/nope", "/sandbox/nope"):
        r = client.get(path)
        assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")


def test_no_file_outside_dist(client):
    for path in ("/../backend/.secret", "/..%2f..%2fbackend%2f.secret", "/%2e%2e/app/config.py"):
        r = client.get(path)
        assert "secret_key" not in r.text and "BaseSettings" not in r.text
