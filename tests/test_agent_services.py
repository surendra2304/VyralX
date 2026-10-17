from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect, text, create_engine

from app.database import SessionLocal
from app.migrations import run_additive_migrations
from app.models import PublishJob, RenderJob
from app.services.content import _extract_json
from app.services.peers import post_peer_json
from app.services.trends import rank_candidates
from app.worker import claim_publish_job, claim_render_job


def test_trend_ranking_is_bounded_and_does_not_grant_rights():
    now = datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc)
    candidates = [
        {
            "video_id": "old",
            "title": "Old viral",
            "channel_title": "A channel",
            "published_at": (now - timedelta(days=200)).isoformat(),
            "view_count": 8_000_000,
            "like_count": 100,
            "comment_count": 20,
            "rights_verified": True,
        },
        {
            "video_id": "new",
            "title": "New candidate",
            "channel_title": "A channel",
            "published_at": (now - timedelta(hours=2)).isoformat(),
            "view_count": 120_000,
            "like_count": 8_000,
            "comment_count": 300,
        },
    ]
    ranked = rank_candidates(candidates, now=now)
    assert ranked[0]["video_id"] == "new"
    assert all(0 <= item["trend_score"] <= 100 for item in ranked)
    assert all(item["rights_verified"] is False for item in ranked)
    assert all(item["discovery_only"] is True for item in ranked)


def test_content_pack_parser_requires_complete_contract():
    full_pack = {
        "hook": "A hook",
        "script": "An original script",
        "scene_plan": [],
        "voiceover": "Voice text",
        "caption": "Caption",
        "title_options": ["A title"],
        "description": "Description",
        "tags": ["one", "two"],
        "thumbnail_brief": "Thumbnail concept",
    }
    parsed = _extract_json(__import__("json").dumps(full_pack))
    assert parsed["tags"] == ["one", "two"]
    with pytest.raises(ValueError, match="missing fields"):
        _extract_json('{"hook":"incomplete"}')


def test_peer_client_rejects_url_and_traversal_paths_before_network():
    with pytest.raises(ValueError, match="absolute path"):
        post_peer_json("friday", "//example.invalid/steal", {})
    with pytest.raises(ValueError, match="not a URL"):
        post_peer_json("friday", "/https://example.invalid", {})
    with pytest.raises(ValueError, match="traversal"):
        post_peer_json("friday", "/../admin", {})


def test_worker_claims_render_queue_and_increments_attempts():
    with SessionLocal() as db:
        job = RenderJob(asset_id=987654, preset="shorts", status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    try:
        with SessionLocal() as db:
            assert claim_render_job(db) == job_id
        with SessionLocal() as db:
            claimed = db.get(RenderJob, job_id)
            assert claimed is not None
            assert claimed.status == "running"
            assert claimed.attempts == 1
    finally:
        with SessionLocal() as db:
            db.query(RenderJob).filter(RenderJob.id == job_id).delete()
            db.commit()


def test_worker_does_not_claim_unapproved_publish_job():
    with SessionLocal() as db:
        job = PublishJob(
            asset_id=987654,
            render_job_id=987654,
            title="Test",
            status="pending_approval",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    try:
        with SessionLocal() as db:
            assert claim_publish_job(db) is None
        with SessionLocal() as db:
            queued = db.get(PublishJob, job_id)
            assert queued is not None and queued.status == "pending_approval"
            queued.status = "queued"
            db.commit()
        with SessionLocal() as db:
            assert claim_publish_job(db) == job_id
        with SessionLocal() as db:
            claimed = db.get(PublishJob, job_id)
            assert claimed is not None
            assert claimed.status == "uploading"
            assert claimed.attempts == 1
    finally:
        with SessionLocal() as db:
            db.query(PublishJob).filter(PublishJob.id == job_id).delete()
            db.commit()


def test_additive_migrations_upgrade_existing_job_tables(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE render_jobs (id INTEGER PRIMARY KEY, status VARCHAR(40))"))
            connection.execute(text("CREATE TABLE publish_jobs (id INTEGER PRIMARY KEY, status VARCHAR(40))"))
        run_additive_migrations(engine)
        render_columns = {column["name"] for column in inspect(engine).get_columns("render_jobs")}
        publish_columns = {column["name"] for column in inspect(engine).get_columns("publish_jobs")}
        assert {"attempts", "started_at", "completed_at", "updated_at"} <= render_columns
        assert {"attempts", "approved_at", "started_at", "completed_at", "updated_at"} <= publish_columns
    finally:
        engine.dispose()


def test_agent_task_schema_has_an_allowlisted_contract():
    from app.schemas import AgentTaskRequest

    request = AgentTaskRequest(
        task_id="friday-task-001",
        task_type="content.generate",
        correlation_id="conversation-001",
        input={"topic": "How solar power works"},
    )
    assert request.task_id == "friday-task-001"
    assert request.task_type == "content.generate"
    assert request.correlation_id == "conversation-001"
    with pytest.raises(Exception):
        AgentTaskRequest(task_type="run.shell", input={"command": "id"})


def test_worker_claims_agent_task_and_increments_attempts():
    from app.models import AgentTask
    from app.worker import claim_agent_task

    with SessionLocal() as db:
        task = AgentTask(
            task_id="test-agent-task-" + str(datetime.now(timezone.utc).timestamp()),
            task_type="discover.youtube",
            input_json='{"query":"test"}',
            status="queued",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_row_id = task.id
    try:
        with SessionLocal() as db:
            assert claim_agent_task(db) == task_row_id
        with SessionLocal() as db:
            task = db.get(AgentTask, task_row_id)
            assert task is not None
            assert task.status == "running"
            assert task.attempts == 1
    finally:
        with SessionLocal() as db:
            db.query(AgentTask).filter(AgentTask.id == task_row_id).delete()
            db.commit()


def test_caption_writer_creates_valid_srt_and_rejects_reverse_cues(tmp_path: Path):
    from app.services.captions import write_srt

    output = write_srt(
        [
            {"start_seconds": 0, "end_seconds": 1.25, "text": "<b>Hello world</b>"},
            {"start_seconds": 1.5, "end_seconds": 2.0, "text": "Second cue"},
        ],
        tmp_path / "captions.srt",
    )
    text_out = output.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:01,250" in text_out
    assert "Hello world" in text_out
    assert "<b>" not in text_out
    with pytest.raises(ValueError, match="positive time range"):
        write_srt([{"start_seconds": 3, "end_seconds": 2, "text": "wrong"}], tmp_path / "bad.srt")


def test_pexels_media_url_allowlist_rejects_arbitrary_hosts():
    from app.services.pexels import _safe_file_url

    assert _safe_file_url("https://videos.pexels.com/video-files/123/clip.mp4")
    assert _safe_file_url("https://player.vimeo.com/external/123.hd.mp4")
    assert not _safe_file_url("http://videos.pexels.com/clip.mp4")
    assert not _safe_file_url("https://example.invalid/clip.mp4")
    assert not _safe_file_url("https://player.vimeo.com/evil/clip.mp4")


def test_content_generation_uses_actual_inference_task_contract(monkeypatch):
    import json
    from types import SimpleNamespace

    from app.services import content as content_service

    settings = SimpleNamespace(
        inference_url="http://inference:8000",
        inference_api_key="test-key",
        inference_model="",
        inference_generation_path="/v1/task/execute",
        inference_timeout_seconds=3,
    )
    monkeypatch.setattr(content_service, "get_settings", lambda: settings)

    result_pack = {
        "hook": "A hook",
        "script": "Original script",
        "scene_plan": [{"timecode": "00:00-00:05", "visual": "Solar panels", "on_screen_text": "Solar"}],
        "voiceover": "Original voiceover",
        "caption": "Caption",
        "title_options": ["A title"],
        "description": "Description",
        "tags": ["solar", "science"],
        "thumbnail_brief": "Sunlit solar panels",
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "SUCCESS", "result": {"response": json.dumps(result_pack), "model_used": "test-model"}}

    calls = {}

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr(content_service.httpx, "post", fake_post)
    actual = content_service.generate_content_pack("How solar panels work", target_seconds=45)

    assert calls["url"] == "http://inference:8000/v1/task/execute"
    assert calls["kwargs"]["json"]["target_agent"] == "inference"
    assert calls["kwargs"]["json"]["source_agent"] == "vyralx"
    assert "X-FRIDAY-API-Key" in calls["kwargs"]["headers"]
    assert "Return one valid JSON object" in calls["kwargs"]["json"]["payload"]["prompt"]
    assert actual["provider_model"] == "test-model"
    assert actual["fact_check_passed"] is False
    assert actual["requires_editor_review"] is True
