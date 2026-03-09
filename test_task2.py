"""
TDD RED tests for Task 2: POST /download and GET /files/{file_id} routes.
These tests must fail before implementation.
"""
import os
import inspect
import pytest

os.environ.setdefault("API_KEY", "test-key")


def test_download_video_exists():
    import main
    assert hasattr(main, "download_video"), "download_video missing"


def test_download_video_is_sync():
    import main
    assert not inspect.iscoroutinefunction(main.download_video), "download_video must be sync"


def test_post_download_route_exists():
    import main
    routes = {r.path: r for r in main.app.routes}
    assert "/download" in routes, "POST /download route missing"


def test_get_files_route_exists():
    import main
    routes = {r.path: r for r in main.app.routes}
    assert "/files/{file_id}" in routes, "GET /files/{file_id} route missing"


def test_get_nonexistent_file_returns_404():
    from fastapi.testclient import TestClient
    import main
    client = TestClient(main.app, raise_server_exceptions=False)
    resp = client.get("/files/nonexistent-id", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 404


def test_get_file_requires_auth():
    from fastapi.testclient import TestClient
    import main
    client = TestClient(main.app, raise_server_exceptions=False)
    resp = client.get("/files/some-id")
    assert resp.status_code == 401


def test_download_requires_auth():
    from fastapi.testclient import TestClient
    import main
    client = TestClient(main.app, raise_server_exceptions=False)
    resp = client.post("/download", json={"url": "http://example.com"})
    assert resp.status_code == 401


def test_get_expired_file_returns_410():
    """Register a file with past expiry, then check GET returns 410."""
    from fastapi.testclient import TestClient
    from datetime import datetime, timedelta
    import main

    # Register an expired file record
    record = main.FileRecord(
        file_id="expired-test-id",
        path="/tmp/nonexistent.mp4",
        filename="expired.mp4",
        title="Expired",
        duration=0,
        expires_at=datetime.utcnow() - timedelta(hours=2),
        content_type="video/mp4",
    )
    main.register_file(record)

    client = TestClient(main.app, raise_server_exceptions=False)
    resp = client.get("/files/expired-test-id", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 410
