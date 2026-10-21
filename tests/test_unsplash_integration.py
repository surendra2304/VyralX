"""Tests for Unsplash photo discovery, authorized import, and Ken Burns montage integration."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.services.unsplash import _safe_image_url, import_photo, search_photos


def test_safe_image_url_validation():
    # Trusted Unsplash URLs
    assert _safe_image_url("https://images.unsplash.com/photo-123456789") is True
    assert _safe_image_url("https://unsplash.com/photos/abc") is True

    # Untrusted / Malicious URLs
    assert _safe_image_url("http://images.unsplash.com/photo") is False  # Insecure HTTP
    assert _safe_image_url("https://evil.com/photo.jpg") is False
    assert _safe_image_url("https://user:pass@images.unsplash.com/photo") is False
    assert _safe_image_url("https://images.unsplash.com:8080/photo") is False


def test_search_photos_requires_access_key(monkeypatch: pytest.MonkeyPatch):
    settings = SimpleNamespace(unsplash_access_key="")
    monkeypatch.setattr("app.services.unsplash.get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="Set UNSPLASH_ACCESS_KEY"):
        search_photos("autonomous robotics")


def test_search_photos_success(monkeypatch: pytest.MonkeyPatch):
    settings = SimpleNamespace(unsplash_access_key="test_unsplash_key")
    monkeypatch.setattr("app.services.unsplash.get_settings", lambda: settings)

    fake_response = {
        "results": [
            {
                "id": "photo-quantum-1",
                "alt_description": "Quantum computer glowing in a lab",
                "description": "High tech quantum processor",
                "width": 1080,
                "height": 1920,
                "user": {
                    "name": "Jane Tech",
                    "username": "janetech",
                    "links": {"html": "https://unsplash.com/@janetech"},
                },
                "urls": {
                    "regular": "https://images.unsplash.com/photo-quantum-1?w=1080",
                    "full": "https://images.unsplash.com/photo-quantum-1?w=4000",
                },
                "links": {
                    "html": "https://unsplash.com/photos/photo-quantum-1",
                    "download_location": "https://api.unsplash.com/photos/photo-quantum-1/download",
                },
            }
        ]
    }

    def mock_get(url, params=None, headers=None, **kwargs):
        assert "Authorization" in headers
        assert headers["Authorization"] == "Client-ID test_unsplash_key"
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json = lambda: fake_response
        resp.raise_for_status = lambda: None
        return resp

    monkeypatch.setattr("httpx.get", mock_get)

    results = search_photos("quantum computing", orientation="portrait", per_page=5)
    assert len(results) == 1
    item = results[0]
    assert item["id"] == "photo-quantum-1"
    assert "Quantum computer" in item["title"]
    assert item["creator"] == "Jane Tech"
    assert "https://images.unsplash.com" in item["download_url"]


def test_import_photo_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    settings = SimpleNamespace(media_dir=media_dir)
    monkeypatch.setattr("app.services.unsplash.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.services.unsplash.probe_media",
        lambda p: {"width": 1080, "height": 1920, "duration_seconds": 0.0},
    )

    class MockStreamResponse:
        def __init__(self):
            self.headers = {"content-type": "image/jpeg"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def raise_for_status(self):
            pass

        def iter_bytes(self, chunk_size=1024):
            yield b"dummy-jpg-image-bytes"

    monkeypatch.setattr("httpx.stream", lambda *args, **kwargs: MockStreamResponse())

    imported = import_photo(
        "photo-123",
        "https://images.unsplash.com/photo-123",
        title="Test Space Photo",
        creator="Space Explorer",
    )

    assert imported["platform"] == "unsplash"
    assert imported["license_name"] == "Unsplash License"
    assert imported["width"] == 1080
    assert imported["height"] == 1920
    assert Path(imported["file_path"]).is_file()


def test_api_discover_and_import_unsplash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    client = TestClient(app)
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    # Mock search
    monkeypatch.setattr(
        "app.services.unsplash.search_photos",
        lambda query, **kw: [
            {
                "id": "u-456",
                "title": f"Unsplash {query}",
                "download_url": "https://images.unsplash.com/photo-u456",
                "creator": "Photographer X",
            }
        ],
    )

    # Test GET /api/discover/unsplash
    resp_discover = client.post(
        "/api/discover/unsplash",
        json={"query": "supercomputer", "orientation": "portrait"},
        headers=headers,
    )
    assert resp_discover.status_code == 200
    data = resp_discover.json()
    assert data["count"] == 1
    assert data["items"][0]["id"] == "u-456"

    # Mock import
    media_file = tmp_path / "imported.jpg"
    media_file.write_bytes(b"image-content")
    monkeypatch.setattr(
        "app.services.unsplash.import_photo",
        lambda *args, **kwargs: {
            "file_path": str(media_file),
            "file_size": len(b"image-content"),
            "width": 1080,
            "height": 1920,
            "title": "Supercomputer Visual",
            "creator": "Photographer X",
            "source_url": "https://unsplash.com/photos/u-456",
            "creator_url": "https://unsplash.com/@photographerx",
            "license_name": "Unsplash License",
            "platform": "unsplash",
        },
    )

    resp_import = client.post(
        "/api/assets/import/unsplash",
        json={
            "photo_id": "u-456",
            "download_url": "https://images.unsplash.com/photo-u456",
            "title": "Supercomputer Visual",
        },
        headers=headers,
    )
    assert resp_import.status_code == 201
    import_data = resp_import.json()
    assert import_data["status"] == "imported"
    assert "asset_id" in import_data
