"""Coverage tests for core FastAPI endpoints in app.main."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Asset, ContentPack, PublishJob, RenderJob, Source, VideoProject

client = TestClient(app)


def test_api_integrations_and_manifest():
    res = client.get("/api/integrations")
    assert res.status_code == 200
    data = res.json()
    assert "providers" in data
    assert "inference" in data["providers"]
    assert "sentinel" in data["providers"]

    res_manifest = client.get("/api/agent/manifest")
    assert res_manifest.status_code == 200
    manifest = res_manifest.json()
    assert manifest["service_id"] == "vyralx"
    assert "capabilities" in manifest


def test_api_agents_health(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.main.peer_health",
        lambda name: {"name": name, "reachable": True, "status": "ok"},
    )
    res = client.get("/api/agents/health")
    assert res.status_code == 200
    health = res.json()
    assert health["inference"]["reachable"] is True
    assert health["sentinel"]["status"] == "ok"


def test_api_projects_lifecycle():
    key = "test-proj-" + uuid4().hex[:10]
    payload = {
        "project_key": key,
        "topic": "Autonomous AI Videos",
        "video_format": "shorts",
        "target_seconds": 45,
        "scene_count": 3,
        "audience": "Developers",
        "tone": "Technical and clear",
        "confirm_pexels_license": True,
        "confirm_pexels_repeat_use": True,
        "use_voiceover": False,
        "auto_discover_trend": False,
        "trend_query": "",
    }

    # License must be confirmed
    unconfirmed = dict(payload, confirm_pexels_license=False)
    res_unconfirmed = client.post("/api/projects", json=unconfirmed)
    assert res_unconfirmed.status_code == 403

    # Create project
    res = client.post("/api/projects", json=payload)
    assert res.status_code == 202
    created = res.json()
    assert created["idempotent_replay"] is False
    project_id = created["project_id"]

    # Idempotent replay
    res_replay = client.post("/api/projects", json=payload)
    assert res_replay.status_code == 202
    assert res_replay.json()["idempotent_replay"] is True

    # List projects
    res_list = client.get("/api/projects")
    assert res_list.status_code == 200
    assert any(p["project_id"] == project_id for p in res_list.json()["items"])

    # Get single project
    res_get = client.get(f"/api/projects/{project_id}")
    assert res_get.status_code == 200
    assert res_get.json()["topic"] == "Autonomous AI Videos"

    # Nonexistent project
    assert client.get("/api/projects/999999").status_code == 404

    # Retry project when not failed -> 409
    res_retry = client.post(f"/api/projects/{project_id}/retry", json={"reset_attempts": True})
    assert res_retry.status_code == 409

    # Set project to failed and retry
    with SessionLocal() as db:
        proj = db.get(VideoProject, project_id)
        proj.status = "failed"
        proj.attempts = 1
        db.commit()

    res_retry_ok = client.post(f"/api/projects/{project_id}/retry", json={"reset_attempts": True})
    assert res_retry_ok.status_code == 200
    assert res_retry_ok.json()["status"] == "queued"

    # Cleanup
    with SessionLocal() as db:
        p = db.get(VideoProject, project_id)
        if p:
            db.delete(p)
            db.commit()


def test_api_sources_and_repeat_use_review():
    source_payload = {
        "title": "API Test Creative Commons Footage",
        "source_url": "https://media.example/video/100",
        "platform": "manual",
        "creator": "Creative Video Studio",
        "license_name": "Creative Commons Attribution 4.0",
        "permission_reference": "CC-BY-4.0-LICENSE-PROOF",
        "rights_verified": True,
        "repeat_use_allowed": True,
        "repeat_use_review_notes": "Valid repeat-use review note.",
    }

    res = client.post("/api/sources", json=source_payload)
    assert res.status_code == 200
    source_id = res.json()["id"]

    res_list = client.get("/api/sources")
    assert res_list.status_code == 200
    assert any(s["id"] == source_id for s in res_list.json())

    # Review repeat use
    review_res = client.post(
        f"/api/sources/{source_id}/repeat-use-review",
        json={"repeat_use_allowed": True, "review_notes": "Verified by Lead Media Architect"},
    )
    assert review_res.status_code == 200
    assert review_res.json()["repeat_use_allowed"] is True

    # Review 404
    assert client.post("/api/sources/999999/repeat-use-review", json={"repeat_use_allowed": True, "review_notes": "Valid review note for 404 test"}).status_code == 404

    # Cleanup
    with SessionLocal() as db:
        s = db.get(Source, source_id)
        if s:
            db.delete(s)
            db.commit()


def test_api_job_retries():
    with SessionLocal() as db:
        render = RenderJob(
            asset_id=1,
            preset="shorts",
            status="failed",
            error="Test failure",
            output_path="",
            options_json="{}",
        )
        publish = PublishJob(
            asset_id=1,
            render_job_id=1,
            title="Test Retry Publish",
            status="failed",
            error="Network drop",
        )
        db.add_all([render, publish])
        db.commit()
        render_id, publish_id = render.id, publish.id

    try:
        # Retry render job
        res_r = client.post(f"/api/jobs/render/{render_id}/retry")
        assert res_r.status_code == 202
        assert res_r.json()["status"] == "queued"

        # Retry publish job
        res_p = client.post(f"/api/jobs/publish/{publish_id}/retry")
        assert res_p.status_code == 202
        assert res_p.json()["status"] == "pending_approval"

        # 404s
        assert client.post("/api/jobs/render/999999/retry").status_code == 404
        assert client.post("/api/jobs/publish/999999/retry").status_code == 404
    finally:
        with SessionLocal() as db:
            r = db.get(RenderJob, render_id)
            p = db.get(PublishJob, publish_id)
            if p:
                db.delete(p)
            if r:
                db.delete(r)
            db.commit()


def test_api_pexels_discover(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.main.search_videos",
        lambda query, max_results=10, orientation="portrait": [
            {"video_id": 999, "url": "https://www.pexels.com/video/999/", "title": "Cyber City"}
        ],
    )
    res = client.post("/api/discover/pexels", json={"query": "Cyber City", "orientation": "portrait"})
    assert res.status_code == 200
    assert res.json()["count"] == 1
    assert res.json()["items"][0]["video_id"] == 999


def test_api_content_and_render_and_publish_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_video = tmp_path / "rendered_clip.mp4"
    fake_video.write_bytes(b"DATA" * 500)

    monkeypatch.setattr(
        "app.main.settings",
        SimpleNamespace(
            render_dir=tmp_path,
            media_dir=tmp_path,
            youtube_upload_enabled=True,
            youtube_default_privacy="private",
            max_render_seconds=120,
            worker_max_attempts=3,
        ),
    )

    # 1. Content generation & list
    dummy_pack = {
        "hook": "AI generates videos",
        "script": "Script text",
        "scene_plan": [],
        "voiceover": "VO text",
        "caption": "Captions",
        "title_options": ["AI Video"],
        "description": "Desc",
        "tags": ["ai"],
        "thumbnail_brief": "Art",
        "provider_model": "test-model",
    }
    monkeypatch.setattr("app.main.generate_content_pack", lambda *a, **kw: dummy_pack)

    res_gen = client.post("/api/content/generate", json={"topic": "Deep Learning"})
    assert res_gen.status_code == 200
    pack_id = res_gen.json()["id"]

    res_content = client.get("/api/content")
    assert res_content.status_code == 200
    assert any(c["id"] == pack_id for c in res_content.json())

    # 2. Assets and render creation
    with SessionLocal() as db:
        src = Source(
            title="Render Test Source",
            platform="manual",
            license_name="Standard Commercial License",
            permission_reference="PERM-RENDER-123",
            rights_verified=True,
        )
        db.add(src)
        db.flush()

        asset = Asset(
            source_id=src.id,
            title="Render Test Asset",
            file_path=str(fake_video),
            duration_seconds=30.0,
            width=1080,
            height=1920,
            rights_verified=True,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id
        src_id = src.id

    try:
        # List assets
        res_assets = client.get("/api/assets")
        assert res_assets.status_code == 200
        assert any(a["id"] == asset_id for a in res_assets.json())

        # Create render job
        render_payload = {
            "asset_id": asset_id,
            "preset": "shorts",
            "trim_start_seconds": 0.0,
            "trim_end_seconds": 15.0,
            "subtitle_segments": [],
        }
        res_render = client.post("/api/render", json=render_payload)
        assert res_render.status_code == 202
        render_job_id = res_render.json()["job_id"]

        # List renders
        res_renders = client.get("/api/render")
        assert res_renders.status_code == 200
        assert any(r["id"] == render_job_id for r in res_renders.json())

        # Complete render job to test download & publish
        with SessionLocal() as db:
            rj = db.get(RenderJob, render_job_id)
            rj.status = "completed"
            rj.output_path = str(fake_video)
            db.commit()

        # Download render
        res_dl = client.get(f"/api/render/{render_job_id}/download")
        assert res_dl.status_code == 200
        assert len(res_dl.content) == 2000

        # Queue publish
        publish_payload = {
            "asset_id": asset_id,
            "render_job_id": render_job_id,
            "title": "Published Short",
            "description": "Short Description",
            "tags": ["short"],
            "privacy_status": "private",
            "confirm_rights": True,
        }
        res_pub = client.post("/api/publish", json=publish_payload)
        assert res_pub.status_code == 200
        pub_id = res_pub.json()["job_id"]

        # List publish jobs
        res_pubs = client.get("/api/publish")
        assert res_pubs.status_code == 200
        assert any(p["id"] == pub_id for p in res_pubs.json())

        # Execute publish (approve upload)
        res_exec = client.post(f"/api/publish/{pub_id}/execute", json={"confirm_review": True})
        assert res_exec.status_code == 202
        assert res_exec.json()["status"] == "queued"

    finally:
        with SessionLocal() as db:
            p = db.get(PublishJob, pub_id) if "pub_id" in locals() else None
            r = db.get(RenderJob, render_job_id) if "render_job_id" in locals() else None
            a = db.get(Asset, asset_id)
            s = db.get(Source, src_id)
            c = db.get(ContentPack, pack_id)
            if p:
                db.delete(p)
            if r:
                db.delete(r)
            if a:
                db.delete(a)
            if s:
                db.delete(s)
            if c:
                db.delete(c)
            db.commit()


def test_api_reconcile_and_thumbnails_and_analytics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.models import VideoMetric

    dummy_render_file = tmp_path / "thumb_render.mp4"
    dummy_render_file.write_bytes(b"VID" * 100)

    monkeypatch.setattr(
        "app.main.settings",
        SimpleNamespace(
            render_dir=tmp_path,
            youtube_analytics_enabled=True,
            youtube_upload_enabled=True,
        ),
    )

    with SessionLocal() as db:
        # Uncertain publish job
        uncertain_pub = PublishJob(
            asset_id=1,
            render_job_id=1,
            title="Uncertain Job",
            status="uncertain",
            error="Interrupted",
        )
        # Completed render job
        completed_render = RenderJob(
            asset_id=1,
            preset="shorts",
            status="completed",
            output_path=str(dummy_render_file),
            options_json="{}",
        )
        # Uploaded job for analytics
        uploaded_pub = PublishJob(
            asset_id=1,
            render_job_id=1,
            title="Uploaded Video",
            status="uploaded",
            youtube_video_id="yt-metric-test-1",
        )
        db.add_all([uncertain_pub, completed_render, uploaded_pub])
        db.commit()
        uncertain_id = uncertain_pub.id
        render_id = completed_render.id
        uploaded_id = uploaded_pub.id

    try:
        # 1. Resolve uncertain: decision="uploaded"
        res_res1 = client.post(
            f"/api/jobs/publish/{uncertain_id}/resolve",
            json={"decision": "uploaded", "youtube_video_id": "vid-reconciled-789"},
        )
        assert res_res1.status_code == 200
        assert res_res1.json()["status"] == "uploaded"
        assert res_res1.json()["youtube_video_id"] == "vid-reconciled-789"

        # Set back to uncertain and test decision="not_uploaded"
        with SessionLocal() as db:
            uj = db.get(PublishJob, uncertain_id)
            uj.status = "uncertain"
            db.commit()

        res_res2 = client.post(
            f"/api/jobs/publish/{uncertain_id}/resolve",
            json={"decision": "not_uploaded", "youtube_video_id": ""},
        )
        assert res_res2.status_code == 200
        assert res_res2.json()["status"] == "pending_approval"

        # 2. Thumbnail extraction & retrieval
        monkeypatch.setattr("app.main.probe_media", lambda p: {"duration_seconds": 20.0})

        def fake_extract_thumbnail(render_path, dest_path, timestamp):
            Path(dest_path).write_bytes(b"THUMBNAIL_BYTES")
            return str(dest_path)

        monkeypatch.setattr("app.main.extract_thumbnail", fake_extract_thumbnail)

        res_thumb = client.post(
            "/api/thumbnails",
            json={"render_job_id": render_id, "timestamp_seconds": 5.0},
        )
        assert res_thumb.status_code == 201

        res_get_thumb = client.get(f"/api/thumbnails/{render_id}")
        assert res_get_thumb.status_code == 200
        assert res_get_thumb.content == b"THUMBNAIL_BYTES"

        # 3. Analytics refresh & list
        mock_metrics = [
            {
                "youtube_video_id": "yt-metric-test-1",
                "title": "Uploaded Video",
                "view_count": 500,
                "like_count": 40,
                "comment_count": 10,
            }
        ]
        monkeypatch.setattr("app.main.fetch_video_metrics", lambda ids: mock_metrics)

        res_refresh = client.post("/api/analytics/refresh")
        assert res_refresh.status_code == 200
        assert res_refresh.json()["snapshots_saved"] == 1

        res_analytics = client.get("/api/analytics")
        assert res_analytics.status_code == 200
        assert any(item["youtube_video_id"] == "yt-metric-test-1" for item in res_analytics.json())

    finally:
        with SessionLocal() as db:
            u = db.get(PublishJob, uncertain_id)
            r = db.get(RenderJob, render_id)
            up = db.get(PublishJob, uploaded_id)
            if u:
                db.delete(u)
            if r:
                db.delete(r)
            if up:
                db.delete(up)
            # Delete created metrics
            for m in db.scalars(select(VideoMetric).where(VideoMetric.youtube_video_id == "yt-metric-test-1")).all():
                db.delete(m)
            db.commit()


