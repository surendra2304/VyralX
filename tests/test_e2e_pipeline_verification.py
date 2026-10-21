"""End-to-End Video Pipeline Verification Tests.

Verifies:
1. Viral hook generation and dynamic Ken Burns FFmpeg rendering (app/services/visual_motion.py).
2. Social distribution packaging (/api/projects/{id}/distribution).
3. Cryptographic provenance SHA-256 hash generation for Sentinel security audits (POST /v1/security/audit).
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models import RenderJob, VideoProject
from app.services.distribution import (
    generate_distribution_package,
)
from app.services.hooks import generate_viral_hooks, select_optimal_hook
from app.services.montage import render_montage
from app.services.sentinel import compute_provenance_hash, verify_render_publish_policy
from app.services.task_dispatch import dispatch_agent_task
from app.services.visual_motion import SUPPORTED_MOTIONS, assign_scene_motions, build_motion_filter


# ============================================================================
# 1. Viral Hook Generation & Dynamic Ken Burns FFmpeg Rendering
# ============================================================================

def test_viral_hook_generation_and_scoring():
    """Verify viral hook generation produces 5 distinct, scored psychological archetypes."""
    topic = "Nuclear Fusion Breakthroughs"
    hooks = generate_viral_hooks(topic, audience="tech enthusiasts")
    assert len(hooks) == 5

    archetypes = {h["archetype"] for h in hooks}
    expected_archetypes = {
        "Negative Warning",
        "Contrarian Truth",
        "Curiosity Gap",
        "High Stakes Question",
        "Rapid Breakthrough",
    }
    assert archetypes == expected_archetypes

    # Ensure hooks are ordered descending by score
    scores = [h["overall_score"] for h in hooks]
    assert scores == sorted(scores, reverse=True)

    # Test top hook selection
    optimal = select_optimal_hook(hooks)
    assert optimal["overall_score"] == max(scores)
    assert len(optimal["hook_text"]) > 10

    # Test empty input error
    with pytest.raises(ValueError, match="cannot be empty"):
        generate_viral_hooks("   ")


def test_viral_hooks_api_endpoint():
    """Verify POST /api/content/hooks returns scored hooks and optimal selection."""
    client = TestClient(app)
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    resp = client.post(
        "/api/content/hooks",
        json={"topic": "Quantum Computing", "audience": "developers"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["topic"] == "Quantum Computing"
    assert len(data["candidate_hooks"]) == 5
    assert data["optimal_hook"]["overall_score"] >= 0.70


def test_dynamic_ken_burns_motion_filters():
    """Verify build_motion_filter produces valid FFmpeg zoompan expressions for all supported modes."""
    width, height = 1080, 1920
    fps = 30
    duration_frames = 150

    for mode in SUPPORTED_MOTIONS:
        filter_expr = build_motion_filter(
            mode, width, height, duration_frames=duration_frames, fps=fps
        )
        if mode == "static":
            assert filter_expr == f"scale={width}:{height}"
        else:
            assert filter_expr.startswith("zoompan=")
            assert f"s={width}x{height}" in filter_expr
            assert f"fps={fps}" in filter_expr
            assert f"d={duration_frames}" in filter_expr

    # Verify alternating camera motion trajectory assignments
    assigned = assign_scene_motions(5, alternating=True)
    assert len(assigned) == 5
    assert assigned == ["zoom_in", "pan_right", "zoom_out", "pan_left", "subtle_drift"]


def test_montage_with_dynamic_ken_burns_rendering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify render_montage correctly applies Ken Burns zoompan filters to each montage scene."""
    media_dir = tmp_path / "media"
    render_dir = tmp_path / "renders"
    data_dir = tmp_path / "data"
    media_dir.mkdir()
    render_dir.mkdir()
    data_dir.mkdir()

    clip1 = media_dir / "scene_01.mp4"
    clip2 = media_dir / "scene_02.mp4"
    clip3 = media_dir / "scene_03.mp4"
    clip1.write_bytes(b"data1")
    clip2.write_bytes(b"data2")
    clip3.write_bytes(b"data3")
    output = render_dir / "montage_kenburns.mp4"

    settings = SimpleNamespace(
        media_dir=media_dir,
        render_dir=render_dir,
        data_dir=data_dir,
        ffmpeg_bin="ffmpeg",
        max_render_seconds=300,
        render_max_cpu_threads=2,
        render_max_memory_mb=1024,
        render_enable_ken_burns=True,
    )
    monkeypatch.setattr("app.services.montage.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.montage._verify_disk_space", lambda p: None)

    executed_commands = []

    def mock_subprocess_run(command, **kwargs):
        executed_commands.append(command)
        output.write_bytes(b"rendered-mp4-data")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("app.services.montage.subprocess.run", mock_subprocess_run)

    result_path = render_montage(
        [clip1, clip2, clip3],
        output,
        "shorts",
        target_seconds=30,
        enable_ken_burns=True,
    )

    assert result_path == str(output.resolve())
    assert len(executed_commands) == 1
    cmd = executed_commands[0]

    # Verify -filter_complex contains zoompan filters for all 3 scenes
    idx = cmd.index("-filter_complex")
    filtergraph = cmd[idx + 1]

    assert "zoompan=z='min(zoom+" in filtergraph  # scene 0: zoom_in
    assert "zoompan=z=1.10:x='min(iw-iw/zoom" in filtergraph  # scene 1: pan_right
    assert "zoompan=z='if(lte(on,1)" in filtergraph  # scene 2: zoom_out
    assert "concat=n=3:v=1:a=0[joined]" in filtergraph
    assert "[joined]null[outv]" in filtergraph


# ============================================================================
# 2. Social Distribution Packaging & Manifest
# ============================================================================

def test_distribution_package_manifest_with_provenance(tmp_path: Path):
    """Verify generate_distribution_package produces cross-platform metadata with cryptographic provenance."""
    video_file = tmp_path / "final_render.mp4"
    video_content = b"sample video bytes for provenance test"
    video_file.write_bytes(video_content)
    expected_hash = hashlib.sha256(video_content).hexdigest()

    manifest_path = generate_distribution_package(
        project_key="proj-verify-999",
        title="Next Gen Autonomous Video",
        description="Comprehensive analysis of autonomous agent swarms in production.",
        tags=["ai", "agents", "automation", "tech"],
        hook_text="Stop writing manual video pipelines before it is too late!",
        output_dir=tmp_path,
        is_short=True,
        attributions="Stock footage licensed via Pexels.",
        niche="technology",
        video_path=video_file,
    )

    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Verify YouTube metadata
    yt = manifest["youtube"]
    assert yt["platform"] == "youtube"
    assert yt["is_short"] is True
    assert "#Shorts" in yt["title"]
    assert yt["category_id"] == "28"
    assert "Stock Footage & Music Attribution" in yt["description"]

    # Verify Instagram Reels metadata
    ig = manifest["instagram_reels"]
    assert ig["platform"] == "instagram_reels"
    assert "Stop writing manual video pipelines" in ig["first_fold_hook"]
    assert len(ig["hashtags"]) >= 4

    # Verify TikTok metadata
    tt = manifest["tiktok"]
    assert tt["platform"] == "tiktok"
    assert "Stop writing manual video pipelines" in tt["caption"]
    assert "#fyp" in tt["caption"]

    # Verify Cryptographic Provenance in media_asset block
    media_asset = manifest["media_asset"]
    assert media_asset is not None
    assert media_asset["file_path"] == str(video_file.resolve())
    assert media_asset["file_size_bytes"] == len(video_content)
    assert media_asset["sha256"] == expected_hash
    assert media_asset["provenance_verified"] is True


def test_api_projects_distribution_route_with_provenance(tmp_path: Path):
    """Verify POST and GET /api/projects/{id}/distribution generate and return provenance metadata."""
    client = TestClient(app)
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    unique_key = f"proj-test-{uuid4().hex[:8]}"
    video_data = b"synthetic-rendered-media-binary"
    video_file = tmp_path / f"{unique_key}.mp4"
    video_file.write_bytes(video_data)
    expected_hash = hashlib.sha256(video_data).hexdigest()

    db = next(get_db())
    try:
        project = VideoProject(
            project_key=unique_key,
            topic="Space Colony Construction",
            video_format="shorts",
            target_seconds=45,
            status="completed",
        )
        db.add(project)
        db.flush()

        render = RenderJob(
            asset_id=1,
            preset="shorts",
            status="completed",
            output_path=str(video_file),
            project_id=project.id,
        )
        db.add(render)
        db.flush()

        project.render_job_id = render.id
        db.commit()
        project_id = project.id

        # POST /api/projects/{id}/distribution
        post_resp = client.post(
            f"/api/projects/{project_id}/distribution",
            json={"niche": "technology", "hook_text": "Did you know this crazy fact about Space Colonies?"},
            headers=headers,
        )
        assert post_resp.status_code == 200
        post_data = post_resp.json()
        assert post_data["status"] == "generated"
        assert post_data["project_id"] == project_id
        manifest = post_data["manifest"]
        assert manifest["media_asset"]["sha256"] == expected_hash
        assert manifest["media_asset"]["provenance_verified"] is True

        # GET /api/projects/{id}/distribution
        get_resp = client.get(f"/api/projects/{project_id}/distribution", headers=headers)
        assert get_resp.status_code == 200
        get_manifest = get_resp.json()
        assert get_manifest["project_key"] == unique_key
        assert get_manifest["media_asset"]["sha256"] == expected_hash
    finally:
        db.close()


# ============================================================================
# 3. Cryptographic Provenance Hashes & Sentinel Security Audits
# ============================================================================

def test_compute_provenance_hash_utility(tmp_path: Path):
    """Verify compute_provenance_hash returns accurate streaming SHA-256 digests and handles errors."""
    target_file = tmp_path / "valid_asset.mp4"
    test_payload = b"super-secure-production-stream" * 1024
    target_file.write_bytes(test_payload)

    computed_hash = compute_provenance_hash(target_file)
    expected = hashlib.sha256(test_payload).hexdigest()
    assert computed_hash == expected
    assert len(computed_hash) == 64

    # Non-existent file raises ValueError
    with pytest.raises(ValueError, match="does not exist or is empty"):
        compute_provenance_hash(tmp_path / "missing_file.mp4")

    # Empty file raises ValueError
    empty_file = tmp_path / "empty.mp4"
    empty_file.write_bytes(b"")
    with pytest.raises(ValueError, match="does not exist or is empty"):
        compute_provenance_hash(empty_file)


def test_sentinel_audit_provenance_hash_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify verify_render_publish_policy dispatches valid cryptographic provenance hashes to Sentinel."""
    render_file = tmp_path / "verified_render.mp4"
    data = b"cryptographic-render-payload-bytes"
    render_file.write_bytes(data)
    expected_hash = hashlib.sha256(data).hexdigest()

    settings_mock = SimpleNamespace(
        sentinel_url="http://sentinel:8000",
        sentinel_api_key="sentinel_test_key",
        sentinel_required_for_publish=True,
        sentinel_policy_path="/v1/security/audit",
        ffmpeg_bin="ffmpeg",
    )
    monkeypatch.setattr("app.services.sentinel.get_settings", lambda: settings_mock)
    monkeypatch.setattr("app.services.sentinel.configured_peers", lambda: {"sentinel"})
    monkeypatch.setattr(
        "app.services.sentinel.probe_media",
        lambda p: {"duration_seconds": 30.0, "width": 1080, "height": 1920, "audio_stream_count": 1},
    )

    captured_payloads = []

    def mock_post_peer_json(peer_name, path, payload, **kwargs):
        captured_payloads.append((peer_name, path, payload))
        return {
            "allowed": True,
            "decision": "allow",
            "reason": "Policy verified and cryptographic hash validated",
        }

    monkeypatch.setattr("app.services.sentinel.post_peer_json", mock_post_peer_json)

    fake_signal_analysis = {
        "black_intervals": [],
        "silence_intervals": [],
        "audio_metrics": {"integrated_loudness_lufs": -14.0},
    }

    decision = verify_render_publish_policy(
        job_id=42,
        asset_id=10,
        render_job_id=20,
        title="Autonomous AI Verified Short",
        description="Full policy clearance",
        render_path=render_file,
        signal_analysis=fake_signal_analysis,
    )

    assert decision["allowed"] is True
    assert decision["decision"] == "allow"
    assert len(captured_payloads) == 1
    peer, path, dispatched = captured_payloads[0]
    assert peer == "sentinel"
    assert path == "/v1/security/audit"

    media_meta = dispatched["media_metadata"]
    assert media_meta["sha256"] == expected_hash
    assert media_meta["file_size"] == len(data)
    assert media_meta["duration_seconds"] == 30.0


def test_api_project_security_audit_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify POST /api/projects/{id}/audit invokes Sentinel pre-publish audit with provenance hash."""
    client = TestClient(app)
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    unique_key = f"proj-audit-{uuid4().hex[:8]}"
    video_data = b"audit-verified-binary-content"
    video_file = tmp_path / f"{unique_key}.mp4"
    video_file.write_bytes(video_data)
    expected_hash = hashlib.sha256(video_data).hexdigest()

    # Mock Sentinel peer response
    monkeypatch.setattr(
        "app.services.sentinel.probe_media",
        lambda p: {"duration_seconds": 25.0, "width": 1080, "height": 1920, "audio_stream_count": 1},
    )
    monkeypatch.setattr(
        "app.services.sentinel.analyze_media_signals",
        lambda *args, **kwargs: {
            "black_intervals": [],
            "silence_intervals": [],
            "audio_metrics": {"integrated_loudness_lufs": -14.0},
        },
    )
    monkeypatch.setattr("app.services.sentinel.configured_peers", lambda: {"sentinel"})
    monkeypatch.setattr(
        "app.services.sentinel.post_peer_json",
        lambda peer, path, payload, **kwargs: {
            "allowed": True,
            "decision": "allow",
            "audit_id": "sentinel-audit-888",
        },
    )

    db = next(get_db())
    try:
        project = VideoProject(
            project_key=unique_key,
            topic="Deep Sea Exploration",
            status="completed",
            confirm_pexels_license=True,
        )
        db.add(project)
        db.flush()

        render = RenderJob(
            asset_id=1,
            preset="shorts",
            status="completed",
            output_path=str(video_file),
            project_id=project.id,
        )
        db.add(render)
        db.flush()

        project.render_job_id = render.id
        db.commit()
        project_id = project.id

        # POST /api/projects/{id}/audit
        resp = client.post(f"/api/projects/{project_id}/audit", headers=headers)
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "audited"
        assert result["project_id"] == project_id
        assert result["provenance_sha256"] == expected_hash
        assert result["sentinel_audit"]["allowed"] is True
        assert result["sentinel_audit"]["decision"] == "allow"
    finally:
        db.close()


def test_task_dispatch_project_audit_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify FRIDAY task dispatch handles project.audit and returns audited provenance."""
    unique_key = f"proj-task-{uuid4().hex[:8]}"
    video_data = b"friday-task-envelope-media-data"
    video_file = tmp_path / f"{unique_key}.mp4"
    video_file.write_bytes(video_data)
    expected_hash = hashlib.sha256(video_data).hexdigest()

    monkeypatch.setattr(
        "app.services.sentinel.probe_media",
        lambda p: {"duration_seconds": 20.0, "width": 1080, "height": 1920, "audio_stream_count": 1},
    )
    monkeypatch.setattr(
        "app.services.sentinel.analyze_media_signals",
        lambda *args, **kwargs: {
            "black_intervals": [],
            "silence_intervals": [],
            "audio_metrics": {"integrated_loudness_lufs": -14.0},
        },
    )
    monkeypatch.setattr("app.services.sentinel.configured_peers", lambda: {"sentinel"})
    monkeypatch.setattr(
        "app.services.sentinel.post_peer_json",
        lambda peer, path, payload, **kwargs: {"allowed": True, "decision": "allow"},
    )

    db = next(get_db())
    try:
        project = VideoProject(
            project_key=unique_key,
            topic="Space Robotics",
            status="completed",
            confirm_pexels_license=True,
        )
        db.add(project)
        db.flush()

        render = RenderJob(
            asset_id=1,
            preset="shorts",
            status="completed",
            output_path=str(video_file),
            project_id=project.id,
        )
        db.add(render)
        db.flush()

        project.render_job_id = render.id
        db.commit()

        task_result = dispatch_agent_task("project.audit", {"project_id": project.id}, db)
        assert task_result["status"] == "audited"
        assert task_result["project_id"] == project.id
        assert task_result["provenance_sha256"] == expected_hash
        assert task_result["sentinel_audit"]["allowed"] is True
    finally:
        db.close()
