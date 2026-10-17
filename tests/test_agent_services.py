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
