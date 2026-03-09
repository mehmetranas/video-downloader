"""
TDD RED tests for Task 1: Pydantic models + playlist detection helper.
These tests must fail before implementation.
"""
import os
import pytest

os.environ.setdefault("API_KEY", "test-key")


def test_download_request_exists():
    import main
    assert hasattr(main, "DownloadRequest"), "DownloadRequest missing"


def test_download_response_exists():
    import main
    assert hasattr(main, "DownloadResponse"), "DownloadResponse missing"


def test_check_playlist_exists():
    import main
    assert hasattr(main, "_check_playlist"), "_check_playlist missing"


def test_download_request_default_quality():
    import main
    req = main.DownloadRequest(url="http://example.com")
    assert req.quality == "best"


def test_download_request_quality_choices():
    import main
    for q in ["best", "1080p", "720p", "480p", "audio-only"]:
        req = main.DownloadRequest(url="http://example.com", quality=q)
        assert req.quality == q


def test_download_request_invalid_quality():
    import main
    with pytest.raises(Exception):
        main.DownloadRequest(url="http://example.com", quality="4k")


def test_download_response_fields():
    import main
    from datetime import datetime
    resp = main.DownloadResponse(
        download_url="http://example.com/files/abc",
        expires_at=datetime.utcnow(),
        filename="video.mp4",
        title="Test Video",
        duration=120,
    )
    assert resp.download_url == "http://example.com/files/abc"
    assert resp.filename == "video.mp4"
    assert resp.title == "Test Video"
    assert resp.duration == 120


def test_check_playlist_is_sync():
    import main
    import inspect
    assert not inspect.iscoroutinefunction(main._check_playlist), "_check_playlist must be synchronous"
