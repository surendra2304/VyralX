"""Tests for viral hook engine, Ken Burns visual motion, social distribution packager, and related API routes."""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models import RenderJob, VideoProject
from app.services.distribution import (
    format_instagram_reels_metadata,
    format_tiktok_metadata,
    format_youtube_metadata,
    generate_distribution_package,
)
from app.services.hooks import generate_viral_hooks, score_hook_virality, select_optimal_hook
from app.services.visual_motion import assign_scene_motions, build_motion_filter


# --- Hooks Unit Tests ---

def test_score_hook_virality():
    # Empty or blank hook returns baseline
    assert score_hook_virality("")["score"] == 0.0
    assert score_hook_virality("   ")["score"] == 0.0

    # High virality hook with power words and punchy length
    res = score_hook_virality("Nobody realized this insane secret about AI until right now!")
    assert res["score"] >= 0.80
    assert res["grade"] in ("A", "S")
    assert res["optimal_economy"] is True

    # Overly long hook receives word count penalty
    long_hook = "Here is a very long sentence that keeps going on and on and contains far too many words for an effective viral hook in a nine sixteen vertical short video format."
    penalty_res = score_hook_virality(long_hook)
    assert penalty_res["score"] < res["score"]
    assert penalty_res["optimal_economy"] is False


def test_generate_viral_hooks():
    with pytest.raises(ValueError, match="cannot be empty"):
        generate_viral_hooks("")

    hooks = generate_viral_hooks("Quantum Teleportation Breakthrough")
    assert len(hooks) == 5
    # Should be sorted descending by overall_score
    scores = [h["overall_score"] for h in hooks]
    assert scores == sorted(scores, reverse=True)

    # Check structure
    first = hooks[0]
    assert "hook_text" in first
    assert "archetype" in first
    assert "overall_score" in first
    assert "virality_metrics" in first


def test_select_optimal_hook():
    with pytest.raises(ValueError, match="empty hooks list"):
        select_optimal_hook([])

    candidates = [
        {"hook_text": "Good hook", "overall_score": 0.72},
        {"hook_text": "Best hook", "overall_score": 0.96},
        {"hook_text": "Okay hook", "overall_score": 0.65},
    ]
    optimal = select_optimal_hook(candidates)
    assert optimal["hook_text"] == "Best hook"
    assert optimal["overall_score"] == 0.96


# --- Visual Motion Unit Tests ---

def test_build_motion_filter_effects():
    # Zoom in
    f_in = build_motion_filter("zoom_in", 1080, 1920, duration_frames=90)
    assert "zoompan=" in f_in
    assert "1080x1920" in f_in

    # Zoom out
    f_out = build_motion_filter("zoom_out", 1080, 1920, duration_frames=60)
    assert "zoompan=" in f_out
    assert "max(1.0,zoom-" in f_out

    # Pan left
    f_left = build_motion_filter("pan_left", 1080, 1920, duration_frames=90)
    assert "zoompan=" in f_left

    # Pan right
    f_right = build_motion_filter("pan_right", 1080, 1920, duration_frames=90)
    assert "zoompan=" in f_right

    # Subtle drift
    f_drift = build_motion_filter("subtle_drift", 1080, 1920, duration_frames=60)
    assert "sin" in f_drift

    # Static fallback
    f_static = build_motion_filter("static", 1080, 1920)
    assert "scale=1080:1920" in f_static

    # Unknown effect falls back to zoom_in
    f_unknown = build_motion_filter("non_existent_effect", 1080, 1920)
    assert "zoompan=" in f_unknown


def test_assign_scene_motions():
    motions = assign_scene_motions(4)
    assert len(motions) == 4
    assert motions[0] == "zoom_in"
    assert motions[1] == "pan_right"
    assert motions[2] == "zoom_out"
    assert motions[3] == "pan_left"

    non_alternating = assign_scene_motions(3, alternating=False)
    assert non_alternating == ["zoom_in", "zoom_in", "zoom_in"]


# --- Distribution Packager Unit Tests ---

def test_format_platform_metadata():
    title = "Why AI Will Change Everything In 2026"
    desc = "Deep dive into next-gen autonomous systems and synthetic media."
    tags = ["ai", "tech", "future", "shorts"]

    # YouTube Shorts
    yt = format_youtube_metadata(title, desc, tags, is_short=True)
    assert yt["platform"] == "youtube"
    assert yt["category_id"] == "28"
    assert "#Shorts" in yt["title"]

    # Instagram Reels
    ig = format_instagram_reels_metadata("Future of AI", "Wait until you see how AI codes autonomously in 2026")
    assert ig["platform"] == "instagram_reels"
    assert "Wait until you see" in ig["caption"]
    assert len(ig["hashtags"]) > 0

    # TikTok
    tt = format_tiktok_metadata("You won't believe this AI breakthrough")
    assert tt["platform"] == "tiktok"
    assert "You won't believe" in tt["caption"]
    assert "#fyp" in tt["caption"]


def test_generate_distribution_package(tmp_path):
    manifest_path = generate_distribution_package(
        project_key="proj-test-123",
        title="Revolutionary Space Engine Tested",
        description="Scientists tested a new ion drive with record thrust efficiency.",
        tags=["space", "science", "physics"],
        hook_text="This space engine just broke every law of physics!",
        output_dir=tmp_path,
        niche="technology",
    )

    assert manifest_path.is_file()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["project_key"] == "proj-test-123"
    assert "youtube" in data
    assert "instagram_reels" in data
    assert "tiktok" in data
    assert "optimal_publish_window" in data


# --- API Routes Integration Tests ---

def test_api_content_hooks_endpoint():
    settings = get_settings()
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    # Valid request
    resp = client.post("/api/content/hooks", json={"topic": "Black Holes", "audience": "general"}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["topic"] == "Black Holes"
    assert len(data["candidate_hooks"]) > 0
    assert "optimal_hook" in data

    # Empty topic error
    err_resp = client.post("/api/content/hooks", json={"topic": "   "}, headers=headers)
    assert err_resp.status_code == 422


def test_api_content_strategy_endpoint():
    settings = get_settings()
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    with patch("app.services.stratex.configured_peers", return_value={}):
        resp = client.post("/api/content/strategy", json={"topic": "Autonomous Robotics", "audience": "engineers"}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategic_score"] >= 0.70
        assert data["target_demographic"] == "engineers"

    # Empty topic error
    err_resp = client.post("/api/content/strategy", json={"topic": ""}, headers=headers)
    assert err_resp.status_code == 422


def test_api_content_coherence_endpoint():
    settings = get_settings()
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    script = "Here is what no one told you about fusion energy. It produces zero carbon emissions. Subscribe to learn more!"
    resp = client.post("/api/content/coherence", json={"script": script}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_hook"] is True
    assert data["has_cta"] is True
    assert data["coherence_score"] >= 0.80

    # Empty script error
    err_resp = client.post("/api/content/coherence", json={"script": ""}, headers=headers)
    assert err_resp.status_code == 422


def test_api_projects_distribution_endpoints(tmp_path):
    settings = get_settings()
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    # 404 on non-existent project
    resp_404 = client.post("/api/projects/999999/distribution", json={}, headers=headers)
    assert resp_404.status_code == 404

    # Setup real project in db
    from uuid import uuid4
    unique_key = f"proj-dist-{uuid4().hex[:8]}"
    mock_db = next(get_db())
    try:
        project = VideoProject(
            project_key=unique_key,
            topic="Space Exploration",
            status="completed",
        )
        mock_db.add(project)
        mock_db.commit()
        mock_db.refresh(project)
        project_id = project.id

        # Missing render job -> 404
        resp_no_render = client.post(f"/api/projects/{project_id}/distribution", json={}, headers=headers)
        assert resp_no_render.status_code == 404
        assert "Completed render output is missing" in resp_no_render.json()["detail"]

        # Add completed render job with existing output file
        rendered_file = tmp_path / f"project_{project_id}_rendered.mp4"
        rendered_file.write_bytes(b"fake video data")

        render_job = RenderJob(
            asset_id=1,
            preset="shorts",
            status="completed",
            output_path=str(rendered_file),
            project_id=project_id,
        )
        mock_db.add(render_job)
        mock_db.commit()
        mock_db.refresh(render_job)

        project.render_job_id = render_job.id
        mock_db.commit()

        # Generate distribution package
        resp_pkg = client.post(
            f"/api/projects/{project_id}/distribution",
            json={"niche": "technology"},
            headers=headers,
        )
        assert resp_pkg.status_code == 200
        pkg_data = resp_pkg.json()
        assert pkg_data["status"] == "generated"
        assert "manifest" in pkg_data
        assert "youtube" in pkg_data["manifest"]

        # GET distribution package
        resp_get = client.get(f"/api/projects/{project_id}/distribution", headers=headers)
        assert resp_get.status_code == 200
        assert resp_get.json()["project_key"] == unique_key
    finally:
        mock_db.close()
