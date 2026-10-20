"""Coverage tests for core FastAPI endpoints in app.main."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import PublishJob, RenderJob, Source, VideoProject

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
