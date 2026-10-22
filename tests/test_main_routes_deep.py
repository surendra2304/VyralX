"""Deep coverage tests for asset upload, pexels import, voiceover generation, and error conditions in app.main."""
from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Asset, ContentPack, Source

client = TestClient(app)


def test_asset_upload_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "app.main.settings",
        SimpleNamespace(
            media_dir=media_dir,
            max_upload_mb=50,
        ),
    )

    # 1. Unsupported media extension
    file_txt = io.BytesIO(b"hello world")
    res_txt = client.post("/api/assets/upload", files={"file": ("test.txt", file_txt, "text/plain")})
    assert res_txt.status_code == 415

    # 2. Source not found
    file_mp4 = io.BytesIO(b"dummy mp4 data")
    res_nosrc = client.post(
        "/api/assets/upload",
        files={"file": ("test.mp4", file_mp4, "video/mp4")},
        params={"source_id": 999999},
    )
    assert res_nosrc.status_code == 404

    # 3. Source rights unverified
    with SessionLocal() as db:
        unverified_src = Source(
            title="Unverified Source",
            platform="manual",
            rights_verified=False,
        )
        db.add(unverified_src)
        db.commit()
        unverified_src_id = unverified_src.id

    try:
        file_mp4_2 = io.BytesIO(b"dummy mp4 data")
        res_unver = client.post(
            "/api/assets/upload",
            files={"file": ("test.mp4", file_mp4_2, "video/mp4")},
            params={"source_id": unverified_src_id},
        )
        assert res_unver.status_code == 403
    finally:
        with SessionLocal() as db:
            s = db.get(Source, unverified_src_id)
            if s:
                db.delete(s)
                db.commit()

    # 4. Probe fails -> 422
    def mock_failing_probe(path):
        raise ValueError("Cannot decode header")

    monkeypatch.setattr("app.main.probe_media", mock_failing_probe)
    file_mp4_3 = io.BytesIO(b"corrupt mp4")
    res_corrupt = client.post(
        "/api/assets/upload",
        files={"file": ("test.mp4", file_mp4_3, "video/mp4")},
    )
    assert res_corrupt.status_code == 422

    # 5. Non-positive duration -> 422
    monkeypatch.setattr(
        "app.main.probe_media",
        lambda path: {"width": 1080, "height": 1920, "duration_seconds": 0.0},
    )
    file_mp4_4 = io.BytesIO(b"zero duration mp4")
    res_zero = client.post(
        "/api/assets/upload",
        files={"file": ("test.mp4", file_mp4_4, "video/mp4")},
    )
    assert res_zero.status_code == 422

    # 6. Successful upload with verified source
    with SessionLocal() as db:
        valid_src = Source(
            title="Valid Upload Source",
            platform="manual",
            license_name="Full Commercial License",
            permission_reference="PERM-UP-12345",
            rights_verified=True,
        )
        db.add(valid_src)
        db.commit()
        valid_src_id = valid_src.id

    try:
        monkeypatch.setattr(
            "app.main.probe_media",
            lambda path: {
                "duration_seconds": 12.5,
                "width": 1080,
                "height": 1920,
                "audio_stream_count": 1,
            },
        )
        file_valid = io.BytesIO(b"valid video content bytes")
        res_ok = client.post(
            "/api/assets/upload",
            files={"file": ("valid.mp4", file_valid, "video/mp4")},
            params={"title": "Uploaded Asset 1", "source_id": valid_src_id},
        )
        assert res_ok.status_code == 200
        asset_data = res_ok.json()
        assert asset_data["title"] == "Uploaded Asset 1"
        assert asset_data["rights_verified"] is True
        asset_id = asset_data["id"]

        with SessionLocal() as db:
            a = db.get(Asset, asset_id)
            if a:
                # Remove uploaded file
                Path(a.file_path).unlink(missing_ok=True)
                db.delete(a)
                db.commit()
    finally:
        with SessionLocal() as db:
            s = db.get(Source, valid_src_id)
            if s:
                db.delete(s)
                db.commit()


def test_import_pexels_asset_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.main.settings",
        SimpleNamespace(
            max_upload_mb=50,
            max_stock_clip_mb=50,
        ),
    )

    # 1. License unconfirmed -> 403
    res_no_conf = client.post(
        "/api/assets/import/pexels",
        json={"video_id": 111, "video_file_id": 222, "confirm_license": False},
    )
    assert res_no_conf.status_code == 403

    # 2. Successful import
    fake_downloaded = tmp_path / "pexels_clip.mp4"
    fake_downloaded.write_bytes(b"PEXELS" * 100)

    def mock_import_video_file(video_id, file_id, *, title, max_bytes):
        return {
            "file_path": str(fake_downloaded),
            "title": title,
            "metadata": {"duration_seconds": 15.0, "width": 1080, "height": 1920},
            "file_id": file_id,
            "video_id": video_id,
            "source_url": f"https://www.pexels.com/video/{video_id}/",
            "creator": "Pexels Artist",
            "creator_url": "https://pexels.com/@artist",
        }

    monkeypatch.setattr("app.main.import_video_file", mock_import_video_file)

    res_ok = client.post(
        "/api/assets/import/pexels",
        json={
            "video_id": 111,
            "video_file_id": 222,
            "title": "Neon Sunset",
            "confirm_license": True,
            "confirm_repeat_use": True,
        },
    )
    assert res_ok.status_code == 201
    imported = res_ok.json()
    assert imported["title"] == "Neon Sunset"
    assert imported["rights_verified"] is True
    asset_id = imported["asset_id"]
    source_id = imported["source_id"]

    # Cleanup
    with SessionLocal() as db:
        a = db.get(Asset, asset_id)
        s = db.get(Source, source_id)
        if a:
            db.delete(a)
        if s:
            db.delete(s)
        db.commit()


def test_generate_content_voiceover_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # 1. Content pack 404
    assert client.post("/api/content/999999/voiceover").status_code == 404

    # 2. Empty script -> 422
    with SessionLocal() as db:
        pack_empty = ContentPack(
            topic="No script",
            video_format="shorts",
            status="generated",
            pack_json='{"script": ""}',
        )
        db.add(pack_empty)
        db.commit()
        empty_id = pack_empty.id

    try:
        assert client.post(f"/api/content/{empty_id}/voiceover").status_code == 422
    finally:
        with SessionLocal() as db:
            p = db.get(ContentPack, empty_id)
            if p:
                db.delete(p)
                db.commit()

    # 3. Successful voiceover generation
    with SessionLocal() as db:
        pack_valid = ContentPack(
            topic="Valid VO topic",
            video_format="shorts",
            status="generated",
            pack_json='{"script": "This is a valid script for synthesis."}',
        )
        db.add(pack_valid)
        db.commit()
        valid_id = pack_valid.id

    fake_vo = tmp_path / "voiceover.wav"
    fake_vo.write_bytes(b"WAVE" * 100)

    monkeypatch.setattr(
        "app.main.synthesize_voiceover",
        lambda text: {"file_path": str(fake_vo), "bytes": 400},
    )

    try:
        res = client.post(f"/api/content/{valid_id}/voiceover")
        assert res.status_code == 202
        assert res.json()["voiceover_status"] == "ready"
        assert res.json()["bytes"] == 400

        with SessionLocal() as db:
            refreshed = db.get(ContentPack, valid_id)
            assert refreshed.voiceover_status == "ready"
            assert refreshed.voiceover_path == str(fake_vo)
    finally:
        with SessionLocal() as db:
            p = db.get(ContentPack, valid_id)
            if p:
                db.delete(p)
                db.commit()
