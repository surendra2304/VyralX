"""Comprehensive deep coverage tests targeting uncovered branches in:
- app.main (agent task envelope, project retry, thumbnail/caption downloads, discovery)
- app.services.task_dispatch (render and publish validation invariants)
- app.services.project_pipeline (forced alignment branches, project execution failure cleanup)
- app.worker (render and publish failure handling, repeat-use blockers, sentinel denial)
- app.services.renderer (moviepy fallback validations)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models import AgentTask, Asset, ContentPack, PublishJob, RenderJob, Source, VideoProject
from app.services.forced_alignment import ForcedAlignmentError
from app.services.project_pipeline import execute_project_pipeline
from app.services.renderer import render_video_with_moviepy
from app.services.rights import append_stock_attribution
from app.services.task_dispatch import dispatch_agent_task
from app.worker import process_publish_job, process_render_job

client = TestClient(app)
settings = get_settings()


# ---------------------------------------------------------------------------
# 1. Main Route Deep Coverage: Agent Tasks, Projects, Captions, Discovery
# ---------------------------------------------------------------------------


def test_api_v1_tasks_input_validation_and_replays():
    """Verify input validation across task types and idempotent duplicate protection."""
    task_id = "test-typed-task-" + uuid4().hex[:12]

    # Invalid input for task_type discover.youtube (missing query or wrong type)
    res_bad = client.post(
        "/api/v1/tasks",
        json={"task_id": task_id, "task_type": "discover.youtube", "input": {"max_results": -5}},
    )
    assert res_bad.status_code == 422

    # Valid discover.youtube task
    valid_payload = {
        "task_id": task_id,
        "task_type": "discover.youtube",
        "input": {"query": "AI Robotics", "max_results": 5},
    }
    res_ok = client.post("/api/v1/tasks", json=valid_payload)
    assert res_ok.status_code == 202
    assert res_ok.json()["task_id"] == task_id
    assert res_ok.json()["idempotent_replay"] is False

    # Idempotent replay with identical payload
    res_replay = client.post("/api/v1/tasks", json=valid_payload)
    assert res_replay.status_code == 202
    assert res_replay.json()["idempotent_replay"] is True

    # Conflict with different input
    conflict_payload = {
        "task_id": task_id,
        "task_type": "discover.youtube",
        "input": {"query": "Completely Different Query", "max_results": 5},
    }
    res_conflict = client.post("/api/v1/tasks", json=conflict_payload)
    assert res_conflict.status_code == 409

    # Compatibility status route
    res_status = client.get(f"/v1/task/status/{task_id}")
    assert res_status.status_code == 200
    assert res_status.json()["task_id"] == task_id

    # List tasks with pagination limit
    res_list = client.get("/api/v1/tasks?limit=10")
    assert res_list.status_code == 200
    assert res_list.json()["count"] >= 1

    # Cleanup
    with SessionLocal() as db:
        t = db.query(AgentTask).filter(AgentTask.task_id == task_id).one_or_none()
        if t:
            db.delete(t)
            db.commit()


def test_api_v1_tasks_cancel_lifecycle():
    """Verify cancellation validation: 404 for unknown, 409 for non-queued, 200 for queued."""
    task_id = "test-cancel-" + uuid4().hex[:12]

    # 404 for non-existent
    res_404 = client.post(f"/api/v1/tasks/{task_id}/cancel", json={"reason": "Not needed"})
    assert res_404.status_code == 404

    # Create queued task
    with SessionLocal() as db:
        t = AgentTask(
            task_id=task_id,
            task_type="discover.pexels",
            input_json=json.dumps({"query": "cyberpunk"}),
            status="running",  # not queued!
        )
        db.add(t)
        db.commit()

    # 409 when attempting to cancel running task
    res_409 = client.post(f"/api/v1/tasks/{task_id}/cancel", json={"reason": "User abort"})
    assert res_409.status_code == 409

    # Set to queued and verify successful cancellation
    with SessionLocal() as db:
        t = db.query(AgentTask).filter(AgentTask.task_id == task_id).one()
        t.status = "queued"
        db.commit()

    res_cancel = client.post(f"/api/v1/tasks/{task_id}/cancel", json={"reason": "User abort"})
    assert res_cancel.status_code == 200
    assert res_cancel.json()["status"] == "cancelled"

    # Cleanup
    with SessionLocal() as db:
        t = db.query(AgentTask).filter(AgentTask.task_id == task_id).one_or_none()
        if t:
            db.delete(t)
            db.commit()


def test_api_projects_retry_and_sync_memory():
    """Verify /api/projects/{id}/retry and /api/projects/{id}/sync-memory branches."""
    # 404 on missing project
    assert client.post("/api/projects/999999/retry", json={"reason": "retry"}).status_code == 404
    assert client.post("/api/projects/999999/sync-memory").status_code == 404

    with SessionLocal() as db:
        proj = VideoProject(
            project_key="retry-test-" + uuid4().hex[:8],
            topic="Retry Topic",
            video_format="shorts",
            status="queued",  # not failed
            attempts=1,
        )
        db.add(proj)
        db.commit()
        db.refresh(proj)
        proj_id = proj.id

    # 409 retry on non-failed
    res_not_failed = client.post(f"/api/projects/{proj_id}/retry", json={"reason": "retry"})
    assert res_not_failed.status_code == 409

    # 409 sync-memory on non-completed
    res_not_completed = client.post(f"/api/projects/{proj_id}/sync-memory")
    assert res_not_completed.status_code == 409

    # Set attempts to max retry limit
    with SessionLocal() as db:
        p = db.get(VideoProject, proj_id)
        p.status = "failed"
        p.attempts = settings.worker_max_attempts
        db.commit()

    res_limit = client.post(f"/api/projects/{proj_id}/retry", json={"reason": "retry"})
    assert res_limit.status_code == 409
    assert "retry limit" in res_limit.text

    # Successful retry
    with SessionLocal() as db:
        p = db.get(VideoProject, proj_id)
        p.attempts = 1
        db.commit()

    res_retry_ok = client.post(f"/api/projects/{proj_id}/retry", json={"reason": "retry"})
    assert res_retry_ok.status_code == 200
    assert res_retry_ok.json()["status"] == "queued"

    # Cleanup
    with SessionLocal() as db:
        p = db.get(VideoProject, proj_id)
        if p:
            db.delete(p)
            db.commit()


def test_api_projects_thumbnail_and_captions_download(tmp_path: Path):
    """Verify download endpoints for project thumbnails and captions with 404 and 200 paths."""
    # 404 on missing
    assert client.get("/api/projects/999999/thumbnail").status_code == 404
    assert client.get("/api/projects/999999/captions").status_code == 404

    # Create dummy thumbnail inside settings.render_dir
    settings.render_dir.mkdir(parents=True, exist_ok=True)
    thumb_file = settings.render_dir / f"test-thumb-{uuid4().hex[:6]}.jpg"
    thumb_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

    # Create dummy caption file inside settings.data_dir / "subtitles"
    sub_dir = settings.data_dir / "subtitles"
    sub_dir.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        proj = VideoProject(
            project_key="media-download-" + uuid4().hex[:8],
            topic="Download Topic",
            video_format="shorts",
            status="completed",
            thumbnail_path=str(thumb_file),
            attempts=1,
        )
        db.add(proj)
        db.commit()
        db.refresh(proj)
        proj_id = proj.id

    sub_file = sub_dir / f"project-{proj_id}-attempt-1.srt"
    sub_file.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello World\n\n", encoding="utf-8")

    # Success paths
    res_thumb = client.get(f"/api/projects/{proj_id}/thumbnail")
    assert res_thumb.status_code == 200
    assert res_thumb.headers["content-type"] == "image/jpeg"

    res_captions = client.get(f"/api/projects/{proj_id}/captions")
    assert res_captions.status_code == 200
    assert "Hello World" in res_captions.text

    # Cleanup files and db
    thumb_file.unlink(missing_ok=True)
    sub_file.unlink(missing_ok=True)
    with SessionLocal() as db:
        p = db.get(VideoProject, proj_id)
        if p:
            db.delete(p)
            db.commit()


def test_api_discover_blank_query_and_error(monkeypatch: pytest.MonkeyPatch):
    """Verify /api/discover query validation and upstream 502 handling."""
    # Blank query
    res_blank = client.post("/api/discover", json={"query": "   ", "max_results": 5})
    assert res_blank.status_code == 422

    # Upstream error -> 502
    def fail_discover(*args, **kwargs):
        raise RuntimeError("YouTube API down")

    monkeypatch.setattr("app.main.discover_youtube_videos", fail_discover)
    res_err = client.post("/api/discover", json={"query": "valid query", "max_results": 5})
    assert res_err.status_code == 502


# ---------------------------------------------------------------------------
# 2. Task Dispatch Deep Validation
# ---------------------------------------------------------------------------


def test_task_dispatch_render_validation_branches(tmp_path: Path):
    """Verify task_dispatch render.create validation invariants."""
    source_file = tmp_path / "asset_video.mp4"
    source_file.write_bytes(b"test video payload")

    with SessionLocal() as db:
        source = Source(
            title="Pexels Clip",
            platform="pexels",
            source_url="https://www.pexels.com/video/1001/",
            license_name="Pexels Content License",
            permission_reference="https://www.pexels.com/license",
            rights_verified=True,
            repeat_use_allowed=True,
            repeat_use_review_notes="Permitted for repeated compilation video creation.",
            repeat_use_reviewed_at=datetime.now(timezone.utc),
            status="verified",
        )
        db.add(source)
        db.flush()

        asset = Asset(
            source_id=source.id,
            title="Valid Source Video",
            file_path=str(source_file),
            duration_seconds=10.0,
            rights_verified=True,
        )
        db.add(asset)
        db.flush()

        # 1. duration <= 0 raises ValueError
        asset.duration_seconds = 0.0
        db.flush()
        with pytest.raises(ValueError, match="duration could not be verified"):
            dispatch_agent_task(
                "render.create",
                {"asset_id": asset.id, "preset": "shorts", "trim_start_seconds": 0.0},
                db,
            )

        asset.duration_seconds = 10.0
        db.flush()

        # 2. trim_end_seconds exceeds duration
        with pytest.raises(ValueError, match="trim_end_seconds exceeds source duration"):
            dispatch_agent_task(
                "render.create",
                {"asset_id": asset.id, "preset": "shorts", "trim_start_seconds": 0.0, "trim_end_seconds": 15.0},
                db,
            )

        # 3. trim range <= 0
        with pytest.raises(ValueError, match="trim_end_seconds must be greater than trim_start_seconds|Trim range has no positive duration"):
            dispatch_agent_task(
                "render.create",
                {"asset_id": asset.id, "preset": "shorts", "trim_start_seconds": 5.0, "trim_end_seconds": 5.0},
                db,
            )

        # 4. subtitle cues exceed trimmed output duration
        with pytest.raises(ValueError, match="Subtitle times must fit"):
            dispatch_agent_task(
                "render.create",
                {
                    "asset_id": asset.id,
                    "preset": "shorts",
                    "trim_start_seconds": 0.0,
                    "trim_end_seconds": 4.0,
                    "subtitle_segments": [{"start_seconds": 0.0, "end_seconds": 5.0, "text": "Too long"}],
                },
                db,
            )

        # 5. content_pack_id with unready voiceover
        pack = ContentPack(
            topic="Test",
            pack_json=json.dumps({"topic": "Test"}),
            voiceover_status="pending",
        )
        db.add(pack)
        db.flush()

        with pytest.raises(ValueError, match="Generate voiceover before attaching"):
            dispatch_agent_task(
                "render.create",
                {"asset_id": asset.id, "preset": "shorts", "content_pack_id": pack.id},
                db,
            )

        # 6. content_pack_id with voiceover outside media directory
        pack.voiceover_status = "ready"
        pack.voiceover_path = "/nonexistent/outside/voiceover.mp3"
        db.flush()

        with pytest.raises(ValueError, match="missing or outside VyralX media storage"):
            dispatch_agent_task(
                "render.create",
                {"asset_id": asset.id, "preset": "shorts", "content_pack_id": pack.id},
                db,
            )


def test_task_dispatch_publish_validation_branches(tmp_path: Path):
    """Verify task_dispatch publish.request validation invariants."""
    source_file = tmp_path / "publish_source.mp4"
    source_file.write_bytes(b"publish media")
    render_file = tmp_path / "rendered.mp4"
    render_file.write_bytes(b"rendered video")

    with SessionLocal() as db:
        source = Source(
            title="Pexels Source 2",
            platform="pexels",
            source_url="https://www.pexels.com/video/2002/",
            license_name="Pexels Content License",
            permission_reference="https://www.pexels.com/license",
            rights_verified=True,
            repeat_use_allowed=True,
            repeat_use_review_notes="Approved for multiple compilations.",
            repeat_use_reviewed_at=datetime.now(timezone.utc),
            status="verified",
        )
        db.add(source)
        db.flush()

        asset = Asset(
            source_id=source.id,
            title="Publish Asset",
            file_path=str(source_file),
            duration_seconds=10.0,
            rights_verified=True,
        )
        db.add(asset)
        db.flush()

        render = RenderJob(
            asset_id=asset.id,
            preset="shorts",
            status="completed",
            output_path=str(render_file),
        )
        db.add(render)
        db.flush()

        # 1. confirm_rights must be True
        with pytest.raises(ValueError, match="confirm_rights must be true"):
            dispatch_agent_task(
                "publish.request",
                {
                    "asset_id": asset.id,
                    "render_job_id": render.id,
                    "title": "My Video",
                    "description": "Desc",
                    "tags": ["tag"],
                    "confirm_rights": False,
                },
                db,
            )

        # 2. Incompatible or uncompleted render job
        render.status = "failed"
        db.flush()
        with pytest.raises(ValueError, match="Select a completed render"):
            dispatch_agent_task(
                "publish.request",
                {
                    "asset_id": asset.id,
                    "render_job_id": render.id,
                    "title": "My Video",
                    "description": "Desc",
                    "tags": ["tag"],
                    "confirm_rights": True,
                },
                db,
            )

        # 3. Scheduled upload with non-private privacy
        render.status = "completed"
        db.flush()
        future_iso = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        with pytest.raises(ValueError, match="Scheduled YouTube uploads must use private privacy"):
            dispatch_agent_task(
                "publish.request",
                {
                    "asset_id": asset.id,
                    "render_job_id": render.id,
                    "title": "My Video",
                    "description": "Desc",
                    "tags": ["tag"],
                    "privacy_status": "public",
                    "scheduled_at": future_iso,
                    "confirm_rights": True,
                },
                db,
            )

        # 4. Valid scheduled private publish creates PublishJob
        result = dispatch_agent_task(
            "publish.request",
            {
                "asset_id": asset.id,
                "render_job_id": render.id,
                "title": "My Video",
                "description": "Desc",
                "tags": ["tag"],
                "privacy_status": "private",
                "scheduled_at": future_iso,
                "confirm_rights": True,
            },
            db,
        )
        assert "publish_job_id" in result
        assert result["status"] == "pending_approval"


# ---------------------------------------------------------------------------
# 3. Worker and Project Pipeline Edge Cases
# ---------------------------------------------------------------------------


def test_worker_process_render_job_montage_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify montage render failure handles exception, marks job failed, and cleans up."""
    def fail_montage(*args, **kwargs):
        raise RuntimeError("FFmpeg montage composition crashed")

    monkeypatch.setattr("app.worker.render_montage", fail_montage)
    dummy_source = tmp_path / "dummy_montage.mp4"
    dummy_source.write_bytes(b"source")

    with SessionLocal() as db:
        source = Source(
            title="Montage Source",
            platform="pexels",
            source_url="https://www.pexels.com/video/5005/",
            license_name="Pexels Content License",
            permission_reference="https://www.pexels.com/license",
            rights_verified=True,
            status="verified",
        )
        db.add(source)
        db.flush()

        asset = Asset(
            source_id=source.id,
            title="Montage Asset",
            file_path=str(dummy_source),
            duration_seconds=10.0,
            rights_verified=True,
        )
        db.add(asset)
        db.flush()

        job = RenderJob(
            asset_id=asset.id,
            preset="shorts",
            status="queued",
            options_json=json.dumps({"montage_asset_ids": [asset.id]}),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    process_render_job(job_id)

    with SessionLocal() as db:
        j = db.get(RenderJob, job_id)
        assert j.status == "failed"
        assert "montage composition crashed" in j.error

        db.delete(j)
        db.delete(asset)
        db.delete(source)
        db.commit()


def test_worker_process_publish_job_sentinel_denial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify Sentinel policy rejection causes publish job to fail with policy reason."""
    render_file = tmp_path / "sentinel_test_render.mp4"
    render_file.write_bytes(b"render bytes")

    monkeypatch.setattr(settings, "sentinel_url", "http://sentinel-service:8000")
    monkeypatch.setattr(settings, "sentinel_required_for_publish", True)
    monkeypatch.setattr(settings, "sentinel_policy_path", "/v1/security/audit")

    # Mock Sentinel policy response to deny publishing
    monkeypatch.setattr(
        "app.worker.post_peer_json",
        lambda *args, **kwargs: {"allowed": False, "reason": "Watermark policy violation"},
    )
    monkeypatch.setattr(
        "app.worker.analyze_media_signals",
        lambda *args, **kwargs: {"loudness_lufs": -14.0, "has_black_frames": False, "has_silence_gaps": False},
    )

    with SessionLocal() as db:
        source = Source(
            title="Sentinel Source",
            platform="pexels",
            source_url="https://www.pexels.com/video/3003/",
            license_name="Pexels Content License",
            permission_reference="https://www.pexels.com/license",
            rights_verified=True,
            repeat_use_allowed=True,
            repeat_use_review_notes="Permitted for repeated video compilation creation.",
            repeat_use_reviewed_at=datetime.now(timezone.utc),
            status="verified",
        )
        db.add(source)
        db.flush()

        asset = Asset(
            source_id=source.id,
            title="Sentinel Test Asset",
            file_path=str(render_file),
            duration_seconds=10.0,
            rights_verified=True,
        )
        db.add(asset)
        db.flush()

        render = RenderJob(
            asset_id=asset.id,
            preset="shorts",
            status="completed",
            output_path=str(render_file),
        )
        db.add(render)
        db.flush()

        pub = PublishJob(
            asset_id=asset.id,
            render_job_id=render.id,
            title="Sentinel Publish Test",
            description=append_stock_attribution("Testing Sentinel rejection", [(asset, source)]),
            status="approved",
        )
        db.add(pub)
        db.commit()
        db.refresh(pub)
        pub_id = pub.id

    process_publish_job(pub_id)

    with SessionLocal() as db:
        pj = db.get(PublishJob, pub_id)
        assert pj.status == "failed"
        assert "Watermark policy violation" in pj.error

        # Cleanup
        db.delete(pj)
        db.delete(render)
        db.delete(asset)
        db.delete(source)
        db.commit()


def test_project_pipeline_word_forced_alignment_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify forced alignment path and fallback when ForcedAlignmentError is raised."""
    # Create dummy media files
    render_file = tmp_path / "test_pipe_render.mp4"
    render_file.write_bytes(b"pipeline render bytes")
    voice_file = settings.media_dir / f"test_voice_{uuid4().hex[:6]}.mp3"
    voice_file.write_bytes(b"voice bytes")

    monkeypatch.setattr(
        "app.services.project_pipeline.render_montage",
        lambda *args, **kwargs: str(render_file),
    )
    monkeypatch.setattr(
        "app.services.project_pipeline.probe_media",
        lambda *args, **kwargs: {"duration_seconds": 15.0, "audio_stream_count": 1, "width": 1080, "height": 1920},
    )
    def mock_extract(src, dst, *args, **kwargs):
        Path(dst).write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
        return str(dst)

    monkeypatch.setattr(
        "app.services.project_pipeline.extract_thumbnail",
        mock_extract,
    )
    monkeypatch.setattr(
        "app.services.project_pipeline.analyze_media_signals",
        lambda *args, **kwargs: {"loudness_lufs": -14.0, "has_black_frames": False, "has_silence_gaps": False},
    )
    monkeypatch.setattr(
        "app.services.project_pipeline.sync_project_memory",
        lambda *args, **kwargs: {"synced": True},
    )

    # 1. Forced alignment raises ForcedAlignmentError -> fallback
    monkeypatch.setattr(settings, "caption_alignment_url", "http://test-aligner:8000")
    def fail_alignment(*args, **kwargs):
        raise ForcedAlignmentError("Aligner unavailable")

    monkeypatch.setattr("app.services.project_pipeline.align_word_timestamps", fail_alignment)

    with SessionLocal() as db:
        source = Source(
            title="Pipeline Source",
            platform="pexels",
            source_url="https://www.pexels.com/video/4004/",
            license_name="Pexels Content License",
            permission_reference="https://www.pexels.com/license",
            rights_verified=True,
            repeat_use_allowed=True,
            repeat_use_review_notes="Permitted for repeated video compilation creation.",
            repeat_use_reviewed_at=datetime.now(timezone.utc),
            status="verified",
        )
        db.add(source)
        db.flush()

        asset = Asset(
            source_id=source.id,
            title="Pipeline Asset",
            file_path=str(render_file),
            duration_seconds=15.0,
            rights_verified=True,
        )
        db.add(asset)
        db.flush()

        pack = ContentPack(
            topic="Alignment Test",
            pack_json=json.dumps({
                "topic": "Alignment Test",
                "script": "First cue. Second cue. Third cue.",
                "voiceover": "First cue. Second cue. Third cue.",
                "scene_plan": [{"search_query": "tech"}],
            }),
            voiceover_status="ready",
            voiceover_path=str(voice_file),
        )
        db.add(pack)
        db.flush()

        proj = VideoProject(
            project_key="pipe-align-" + uuid4().hex[:8],
            topic="Alignment Test",
            video_format="shorts",
            target_seconds=15,
            scene_count=1,
            use_voiceover=True,
            confirm_pexels_license=True,
            status="running",
            content_pack_id=pack.id,
            primary_asset_id=asset.id,
            asset_ids_json=json.dumps([asset.id]),
            attempts=1,
        )
        db.add(proj)
        db.commit()
        proj_id = proj.id

    with SessionLocal() as db:
        execute_project_pipeline(proj_id, db)

    with SessionLocal() as db:
        p = db.get(VideoProject, proj_id)
        assert p.status == "completed"
        cp = db.get(ContentPack, p.content_pack_id)
        pack_data = json.loads(cp.pack_json)
        assert pack_data.get("caption_alignment_status") == "alignment_fallback"

        # Cleanup
        db.delete(p)
        db.delete(cp)
        db.delete(asset)
        db.delete(source)
        db.commit()
    voice_file.unlink(missing_ok=True)


def test_renderer_moviepy_validations():
    """Verify moviepy renderer input validation (missing source, invalid preset)."""
    with pytest.raises(FileNotFoundError, match="Source media not found"):
        render_video_with_moviepy("/nonexistent/file.mp4", "/output/file.mp4", "shorts")

    # Real file with invalid preset
    existing_file = Path(__file__).resolve()
    with pytest.raises(ValueError, match="Unknown render preset"):
        render_video_with_moviepy(str(existing_file), "/output/file.mp4", "invalid_preset_xyz")
