"""Coverage tests for init_db, security, discovery, thumbnail, youtube_analytics, and pexels services."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.database import engine
from app.init_db import init_database
from app.security import require_api_key
from app.services.discovery import discover_youtube_videos
from app.services.pexels import import_video_file, search_videos
from app.services.thumbnail import extract_thumbnail
from app.services.youtube_analytics import fetch_video_metrics


def test_init_database():
    receipt = init_database(engine)
    assert receipt["connected"] is True
    assert "video_projects" in receipt["tables_found"]


def test_security_require_api_key(monkeypatch: pytest.MonkeyPatch):
    # 1. Dev mode bypass
    monkeypatch.setattr(
        "app.security.get_settings",
        lambda: SimpleNamespace(app_env="development", api_key="development-only-change-me"),
    )
    # Should not raise
    require_api_key(None, None, None)

    # 2. Prod mode with valid keys
    monkeypatch.setattr(
        "app.security.get_settings",
        lambda: SimpleNamespace(app_env="production", api_key="secret-key-123"),
    )
    # Valid X-API-Key
    require_api_key(x_api_key="secret-key-123", authorization=None, x_friday_api_key=None)
    # Valid Bearer
    require_api_key(x_api_key=None, authorization="Bearer secret-key-123", x_friday_api_key=None)
    # Valid X-FRIDAY-API-Key
    require_api_key(x_api_key=None, authorization=None, x_friday_api_key="secret-key-123")

    # 3. Invalid or missing keys raise 401
    with pytest.raises(HTTPException) as exc:
        require_api_key(x_api_key="wrong-key", authorization=None, x_friday_api_key=None)
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:
        require_api_key(x_api_key=None, authorization="Basic invalid", x_friday_api_key=None)
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:
        require_api_key(x_api_key=None, authorization=None, x_friday_api_key=None)
    assert exc.value.status_code == 401


def test_discovery_youtube_videos(monkeypatch: pytest.MonkeyPatch):
    # 1. Missing API key
    monkeypatch.setattr(
        "app.services.discovery.get_settings",
        lambda: SimpleNamespace(youtube_data_api_key=""),
    )
    with pytest.raises(RuntimeError, match="Set YOUTUBE_DATA_API_KEY"):
        discover_youtube_videos("test")

    # 2. Invalid order
    monkeypatch.setattr(
        "app.services.discovery.get_settings",
        lambda: SimpleNamespace(youtube_data_api_key="fake-key"),
    )
    with pytest.raises(ValueError, match="Unsupported YouTube search ordering"):
        discover_youtube_videos("test", order="invalid_order")

    # 3. Successful search
    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, params=None):
            req = httpx.Request("GET", url)
            if "search" in url:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {"id": {"videoId": "vid1"}, "snippet": {"title": "Title 1", "channelTitle": "Chan 1", "description": "Desc 1"}},
                            {"id": {"videoId": "vid2"}, "snippet": {"title": "Title 2", "channelTitle": "Chan 2", "description": "Desc 2"}},
                        ]
                    },
                    request=req,
                )
            if "videos" in url:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {"id": "vid1", "statistics": {"viewCount": "100", "likeCount": "10", "commentCount": "5"}, "contentDetails": {"duration": "PT1M"}},
                            {"id": "vid2", "statistics": {"viewCount": "500", "likeCount": "50", "commentCount": "20"}, "contentDetails": {"duration": "PT2M"}},
                        ]
                    },
                    request=req,
                )
            return httpx.Response(404, request=req)

    monkeypatch.setattr("app.services.discovery.httpx.Client", MockClient)
    results = discover_youtube_videos("AI trends", max_results=5, order="viewCount")
    assert len(results) == 2
    # viewCount reverse sorted
    assert results[0]["video_id"] == "vid2"
    assert results[0]["view_count"] == 500
    assert results[1]["video_id"] == "vid1"


def test_thumbnail_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    render_video = tmp_path / "sample.mp4"
    dest_thumb = tmp_path / "thumb.jpg"

    # 1. Missing file
    with pytest.raises(FileNotFoundError):
        extract_thumbnail(render_video, dest_thumb, 1.0)

    render_video.write_bytes(b"dummy")

    # 2. Negative timestamp
    with pytest.raises(ValueError, match="non-negative"):
        extract_thumbnail(render_video, dest_thumb, -2.5)

    monkeypatch.setattr(
        "app.services.thumbnail.get_settings",
        lambda: SimpleNamespace(ffmpeg_bin="ffmpeg"),
    )

    # 3. Timeout error
    def mock_run_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=45)

    monkeypatch.setattr("subprocess.run", mock_run_timeout)
    with pytest.raises(RuntimeError, match="exceeded 45 seconds"):
        extract_thumbnail(render_video, dest_thumb, 2.0)

    # 4. Successful run
    def mock_run_success(cmd, **kwargs):
        # Create destination thumbnail
        dest_thumb.write_bytes(b"fake-image-bytes")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", mock_run_success)
    out = extract_thumbnail(render_video, dest_thumb, 2.0)
    assert out == str(dest_thumb.resolve())
    assert dest_thumb.is_file()


def test_youtube_analytics_metrics(monkeypatch: pytest.MonkeyPatch):
    # 1. Missing key
    monkeypatch.setattr(
        "app.services.youtube_analytics.get_settings",
        lambda: SimpleNamespace(youtube_data_api_key=""),
    )
    with pytest.raises(RuntimeError, match="Set YOUTUBE_DATA_API_KEY"):
        fetch_video_metrics(["vid1"])

    # 2. Empty list
    monkeypatch.setattr(
        "app.services.youtube_analytics.get_settings",
        lambda: SimpleNamespace(youtube_data_api_key="valid-key"),
    )
    assert fetch_video_metrics([]) == []

    # 3. Successful fetch
    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, params=None):
            req = httpx.Request("GET", url)
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "vid1",
                            "snippet": {"title": "Short One"},
                            "statistics": {"viewCount": "1200", "likeCount": "95", "commentCount": "12"},
                        }
                    ]
                },
                request=req,
            )

    monkeypatch.setattr("app.services.youtube_analytics.httpx.Client", MockClient)
    metrics = fetch_video_metrics(["vid1"])
    assert len(metrics) == 1
    assert metrics[0]["youtube_video_id"] == "vid1"
    assert metrics[0]["view_count"] == 1200
    assert metrics[0]["like_count"] == 95


def test_pexels_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # 1. Missing Pexels key
    monkeypatch.setattr(
        "app.services.pexels.get_settings",
        lambda: SimpleNamespace(pexels_api_key="", assets_dir=tmp_path / "assets"),
    )
    with pytest.raises(RuntimeError, match="Set PEXELS_API_KEY"):
        search_videos("nature")

    # 2. Invalid orientation
    monkeypatch.setattr(
        "app.services.pexels.get_settings",
        lambda: SimpleNamespace(
            pexels_api_key="test-key",
            assets_dir=tmp_path / "assets",
            media_dir=tmp_path / "media",
        ),
    )
    with pytest.raises(ValueError, match="orientation must be portrait"):
        search_videos("nature", orientation="diagonal")

    # 3. Successful search
    mock_search_json = {
        "videos": [
            {
                "id": 12345,
                "url": "https://www.pexels.com/video/12345/",
                "duration": 15,
                "width": 1080,
                "height": 1920,
                "user": {"name": "Photographer", "url": "https://pexels.com/@photographer"},
                "video_files": [
                    {"id": 1, "width": 1080, "height": 1920, "quality": "hd", "file_type": "video/mp4"},
                ],
            }
        ]
    }

    def mock_get(url, **kwargs):
        req = httpx.Request("GET", url)
        return httpx.Response(200, json=mock_search_json, request=req)

    monkeypatch.setattr("app.services.pexels.httpx.get", mock_get)

    items = search_videos("cyberpunk", max_results=5, orientation="portrait")
    assert len(items) == 1
    assert items[0]["video_id"] == 12345
    assert items[0]["creator"] == "Photographer"
    assert items[0]["license_url"] == "https://www.pexels.com/license/"

    # 4. Import video file with unsafe CDN URL rejection
    mock_video_detail_unsafe = {
        "id": 12345,
        "video_files": [
            {"id": 1, "link": "http://untrusted-domain.com/video.mp4", "file_type": "video/mp4", "width": 1080, "height": 1920},
        ],
    }

    def mock_get_detail_unsafe(url, **kwargs):
        req = httpx.Request("GET", url)
        return httpx.Response(200, json=mock_video_detail_unsafe, request=req)

    monkeypatch.setattr("app.services.pexels.httpx.get", mock_get_detail_unsafe)
    with pytest.raises(RuntimeError, match="outside the approved HTTPS domain"):
        import_video_file(12345, 1, title="Test", max_bytes=100000)

    # 5. Import video file with safe domain
    mock_video_detail_safe = {
        "id": 12345,
        "video_files": [
            {"id": 1, "link": "https://images.pexels.com/videos/12345/video.mp4", "file_type": "video/mp4", "width": 1080, "height": 1920},
        ],
    }

    class MockStreamClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def build_request(self, method, url, headers=None):
            return httpx.Request(method, url, headers=headers)

        def send(self, request, stream=False):
            return httpx.Response(
                200,
                headers={"Content-Length": "2048"},
                stream=httpx.ByteStream(b"V" * 2048),
                request=request,
            )

    (tmp_path / "media").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.services.pexels.httpx.get", lambda *a, **kw: httpx.Response(200, json=mock_video_detail_safe, request=httpx.Request("GET", "https://api.pexels.com")))
    monkeypatch.setattr("app.services.pexels.httpx.Client", MockStreamClient)
    monkeypatch.setattr("app.services.pexels.probe_media", lambda p: {"duration_seconds": 15.0, "width": 1080, "height": 1920})

    imported = import_video_file(12345, 1, title="Pexels Neon City", max_bytes=100000)
    assert imported["video_id"] == 12345
    assert imported["file_id"] == 1
    assert imported["title"] == "Pexels Neon City"
    assert Path(imported["file_path"]).is_file()
