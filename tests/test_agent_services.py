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
    fenced = _extract_json("```json\n" + __import__("json").dumps(full_pack) + "\n```")
    assert fenced["script"] == "An original script"
    prefaced = _extract_json("Here is the requested object:\n" + __import__("json").dumps(full_pack))
    assert prefaced["title_options"] == ["A title"]
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
    actual = content_service.generate_content_pack("How solar panels work", target_seconds=45, research_context=[{"report_id": "intelx-123", "summary": "Solar output varies by sunlight.", "key_findings": ["Output depends on irradiance."]}], memora_context=[{"id": "memory-1", "content_text": "Avoid repeating the last wind-energy topic.", "memory_type": "episodic", "importance": 0.4}])

    assert calls["url"] == "http://inference:8000/v1/task/execute"
    assert calls["kwargs"]["json"]["target_agent"] == "inference"
    assert calls["kwargs"]["json"]["payload"]["context"]["intelx_research_context"][0]["report_id"] == "intelx-123"
    assert calls["kwargs"]["json"]["payload"]["context"]["memora_private_context"][0]["id"] == "memory-1"
    assert calls["kwargs"]["json"]["source_agent"] == "vyralx"
    assert "X-FRIDAY-API-Key" in calls["kwargs"]["headers"]
    assert "Return one valid JSON object" in calls["kwargs"]["json"]["payload"]["prompt"]
    assert actual["provider_model"] == "test-model"
    assert actual["fact_check_passed"] is False
    assert actual["requires_editor_review"] is True


def test_youtube_ambiguous_upload_is_flagged_for_reconciliation(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace

    from app.services import youtube as youtube_service

    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video bytes")
    monkeypatch.setattr(
        youtube_service,
        "get_settings",
        lambda: SimpleNamespace(youtube_upload_enabled=True),
    )

    class FakeUploadRequest:
        def next_chunk(self, num_retries=0):
            raise TimeoutError("network disconnected after sending chunk")

    class FakeVideos:
        def insert(self, **kwargs):
            return FakeUploadRequest()

    class FakeService:
        def videos(self):
            return FakeVideos()

    monkeypatch.setattr(youtube_service, "youtube_service", lambda: FakeService())
    monkeypatch.setattr(
        youtube_service,
        "MediaFileUpload",
        lambda *args, **kwargs: object(),
    )

    with pytest.raises(youtube_service.UploadOutcomeUnknown, match="reconcile before retrying"):
        youtube_service.upload_video(
            str(video),
            title="Test",
            description="",
            tags=[],
            privacy_status="private",
            category_id="28",
        )


def test_caption_segmentation_spans_target_duration():
    from app.services.captions import segment_script

    cues = segment_script(
        "Solar panels turn sunlight into electricity. An inverter converts direct current to usable alternating current.",
        20,
    )
    assert cues
    assert cues[0]["start_seconds"] == 0
    assert cues[-1]["end_seconds"] == 20
    assert all(cue["end_seconds"] > cue["start_seconds"] for cue in cues)
    assert all(cues[i]["start_seconds"] >= cues[i - 1]["start_seconds"] for i in range(1, len(cues)))


def test_project_scene_selection_uses_unique_candidates_and_mp4_files():
    from app.services.project_pipeline import _choose_candidate, _scene_query

    items = [
        {
            "video_id": 101,
            "video_files": [
                {"id": 11, "width": 640, "height": 360, "quality": "sd", "file_type": "video/mp4"},
                {"id": 12, "width": 1920, "height": 1080, "quality": "hd", "file_type": "video/mp4"},
                {"id": 13, "width": 1920, "height": 1080, "quality": "hd", "file_type": "video/webm"},
            ],
        },
        {"video_id": 102, "video_files": [{"id": 14, "width": 1280, "height": 720, "quality": "hd", "file_type": "video/mp4"}]},
    ]
    chosen = _choose_candidate(items, {101})
    assert chosen is not None
    assert chosen[0]["video_id"] == 102
    assert chosen[1]["id"] == 14
    query = _scene_query("solar power", {"visual": "A wide shot of solar panels on a sunny roof"}, 0)
    assert "solar power" in query.lower()
    assert len(query) <= 200


def test_montage_renderer_builds_concat_and_voiceover_command(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace

    from app.services import montage

    media_dir = tmp_path / "media"
    render_dir = tmp_path / "renders"
    data_dir = tmp_path / "data"
    media_dir.mkdir()
    render_dir.mkdir()
    data_dir.mkdir()
    clip_a = media_dir / "a.mp4"
    clip_b = media_dir / "b.mp4"
    voice = media_dir / "voice.wav"
    subtitles = data_dir / "captions.srt"
    clip_a.write_bytes(b"a")
    clip_b.write_bytes(b"b")
    voice.write_bytes(b"wav")
    subtitles.write_text("1\\n00:00:00,000 --> 00:00:01,000\\nHello\\n", encoding="utf-8")
    output = render_dir / "project.mp4"
    settings = SimpleNamespace(
        media_dir=media_dir,
        render_dir=render_dir,
        data_dir=data_dir,
        ffmpeg_bin="ffmpeg",
        max_render_seconds=120,
    )
    monkeypatch.setattr(montage, "get_settings", lambda: settings)
    calls = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        Path(command[-1]).write_bytes(b"rendered")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(montage.subprocess, "run", fake_run)
    result = montage.render_montage(
        [clip_a, clip_b],
        output,
        "shorts",
        target_seconds=20,
        fit_mode="crop",
        subtitle_file=subtitles,
        voiceover_path=voice,
    )
    command = calls["command"]
    assert result == str(output.resolve())
    filtergraph = command[command.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=0[joined]" in filtergraph
    assert "[joined]subtitles=" in filtergraph
    assert "-vf" not in command
    assert "-stream_loop" in command
    assert "[2:a:0]" in command or "2:a:0" in command
    assert output.read_bytes() == b"rendered"


def test_video_project_task_creates_durable_queued_project():
    from uuid import uuid4

    from app.database import SessionLocal
    from app.models import VideoProject
    from app.services.task_dispatch import dispatch_agent_task

    project_key = "test-project-" + uuid4().hex[:12]
    payload = {
        "project_key": project_key,
        "topic": "How wind turbines work",
        "video_format": "shorts",
        "target_seconds": 30,
        "scene_count": 3,
        "confirm_pexels_license": True,
        "use_voiceover": True,
    }
    with SessionLocal() as db:
        result = dispatch_agent_task("project.create", payload, db)
        project = db.get(VideoProject, result["project_id"])
        assert project is not None
        assert project.status == "queued"
        assert project.project_key == project_key
        with pytest.raises(ValueError, match="different project settings"):
            dispatch_agent_task("project.create", {**payload, "trend_max_results": 15}, db)
        db.commit()
    with SessionLocal() as db:
        db.query(VideoProject).filter(VideoProject.project_key == project_key).delete()
        db.commit()


def test_publish_rights_gate_checks_all_montage_assets(tmp_path: Path):
    import json
    from uuid import uuid4

    from app.database import SessionLocal
    from app.models import Asset, RenderJob, Source
    from app.services.rights import append_stock_attribution, verified_render_sources

    suffix = uuid4().hex[:12]
    source_a = Source(
        title="Stock clip A",
        source_url=f"https://www.pexels.com/video/test-clip-{suffix}1/",
        platform="pexels",
        creator="Creator A",
        license_name="Pexels Content License",
        permission_reference="https://www.pexels.com/license/",
        rights_verified=True,
        status="licensed",
    )
    source_b = Source(
        title="Stock clip B",
        source_url=f"https://www.pexels.com/video/test-clip-{suffix}2/",
        platform="pexels",
        creator="Creator B",
        license_name="Pexels Content License",
        permission_reference="https://www.pexels.com/license/",
        rights_verified=True,
        status="licensed",
    )
    with SessionLocal() as db:
        db.add_all([source_a, source_b])
        db.flush()
        asset_a = Asset(source_id=source_a.id, title="Clip A", file_path=str(tmp_path / "a.mp4"), rights_verified=True)
        asset_b = Asset(source_id=source_b.id, title="Clip B", file_path=str(tmp_path / "b.mp4"), rights_verified=True)
        db.add_all([asset_a, asset_b])
        db.flush()
        render = RenderJob(
            asset_id=asset_a.id,
            preset="shorts",
            status="completed",
            output_path=str(tmp_path / "render.mp4"),
            options_json=json.dumps({"montage_asset_ids": [asset_a.id, asset_b.id]}),
        )
        db.add(render)
        db.commit()
        render_id, source_b_id = render.id, source_b.id
        try:
            render = db.get(RenderJob, render_id)
            verified = verified_render_sources(render, db)
            assert len(verified) == 2
            description = append_stock_attribution("An educational video.", verified)
            assert "Creator A" in description and "Creator B" in description
            assert "https://www.pexels.com/license/" in description
            assert append_stock_attribution(description, verified) == description
            # A user-supplied heading alone must not suppress missing credits.
            heading_only = "Intro\\n\\nStock footage credits:"
            completed_heading = append_stock_attribution(heading_only, verified)
            assert "Creator A" in completed_heading and "Creator B" in completed_heading
            source_b = db.get(Source, source_b_id)
            source_b.permission_reference = ""
            db.commit()
            with pytest.raises(ValueError, match="lacks verified license evidence"):
                verified_render_sources(db.get(RenderJob, render_id), db)
        finally:
            db.query(RenderJob).filter(RenderJob.id == render_id).delete()
            db.query(Asset).filter(Asset.id.in_([asset_a.id, asset_b.id])).delete(synchronize_session=False)
            db.query(Source).filter(Source.id.in_([source_a.id, source_b.id])).delete(synchronize_session=False)
            db.commit()


def test_auto_trend_resolution_uses_public_metadata_as_topic_seed(monkeypatch):
    from uuid import uuid4

    from app.database import SessionLocal
    from app.models import VideoProject
    from app.services import project_pipeline

    project_key = "trend-project-" + uuid4().hex[:12]
    with SessionLocal() as db:
        project = VideoProject(
            project_key=project_key, topic="Trending topic", auto_discover_trend=True,
            trend_query="renewable energy", trend_max_results=5, video_format="shorts",
            target_seconds=30, confirm_pexels_license=True, use_voiceover=False, status="queued",
        )
        db.add(project)
        db.commit()
        project_id = project.id
    try:
        monkeypatch.setattr(project_pipeline, "discover_youtube_videos", lambda query, count, order: [
            {"video_id": "abc123", "title": "Why wind turbines are changing cities",
             "url": "https://www.youtube.com/watch?v=abc123", "view_count": 500000,
             "like_count": 10000, "comment_count": 500, "published_at": "2026-10-17T10:00:00Z",
             "channel_title": "Example Channel"}
        ])
        monkeypatch.setattr(project_pipeline, "rank_candidates", lambda items: [{**items[0], "trend_score": 9.5}])
        with SessionLocal() as db:
            project = db.get(VideoProject, project_id)
            project_pipeline._resolve_trending_topic(project, db)
            assert project.topic == "Why wind turbines are changing cities"
            assert project.trend_source_video_id == "abc123"
            assert project.trend_source_url == "https://www.youtube.com/watch?v=abc123"
            assert project.trend_score == 9.5
        with SessionLocal() as db:
            project = db.get(VideoProject, project_id)
            assert project.auto_discover_trend is True
            assert project.topic == "Why wind turbines are changing cities"
    finally:
        with SessionLocal() as db:
            db.query(VideoProject).filter(VideoProject.project_key == project_key).delete()
            db.commit()


def test_pexels_uses_official_video_api_endpoints():
    from app.services.pexels import PEXELS_SEARCH_URL, PEXELS_VIDEO_URL

    assert PEXELS_SEARCH_URL == "https://api.pexels.com/videos/search"
    assert PEXELS_VIDEO_URL == "https://api.pexels.com/videos/videos/{video_id}"


def test_probe_reports_audio_stream_count(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace

    from app.services import probe

    media = tmp_path / "sample.mp4"
    media.write_bytes(b"fixture")
    monkeypatch.setattr(probe, "get_settings", lambda: SimpleNamespace(ffprobe_bin="ffprobe"))
    monkeypatch.setattr(probe.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stderr="", stdout='{"format":{"duration":"12.0"},"streams":[{"codec_type":"video","width":1080,"height":1920},{"codec_type":"audio"}]}'
    ))
    metadata = probe.probe_media(media)
    assert metadata["duration_seconds"] == 12.0
    assert metadata["width"] == 1080 and metadata["height"] == 1920
    assert metadata["audio_stream_count"] == 1


def test_peer_get_json_uses_validated_path_and_query_params(monkeypatch):
    from app.services import peers

    peer = peers.Peer(name="intelx", base_url="http://intelx:8000", api_key="peer-test-key")
    monkeypatch.setattr(peers, "configured_peers", lambda: {"intelx": peer})
    calls = {}
    class FakeResponse:
        content = b"[]"
        def raise_for_status(self):
            return None
        def json(self):
            return [{"report_id": "report-1", "summary": "Research summary"}]
    def fake_get(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return FakeResponse()
    monkeypatch.setattr(peers.httpx, "get", fake_get)
    result = peers.get_peer_json("intelx", "/api/v1/research/query", {"sector": "wind power", "limit": 5})
    assert result[0]["report_id"] == "report-1"
    assert calls["url"] == "http://intelx:8000/api/v1/research/query"
    assert calls["kwargs"]["params"]["sector"] == "wind power"
    assert calls["kwargs"]["headers"]["X-API-Key"] == "peer-test-key"
    with pytest.raises(ValueError, match="traversal"):
        peers.get_peer_json("intelx", "/api/v1/../secrets")


def test_local_voiceover_rate_tracks_target_duration(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace

    from app.services import voiceover

    media_dir = tmp_path / "media"
    media_dir.mkdir()
    settings = SimpleNamespace(media_dir=media_dir, tts_provider="espeak", espeak_bin="espeak-ng", espeak_voice="en-us", espeak_rate=165)
    monkeypatch.setattr(voiceover, "get_settings", lambda: settings)
    monkeypatch.setattr(voiceover.shutil, "which", lambda name: "/usr/bin/espeak-ng")
    calls = {}
    def fake_run(command, **kwargs):
        calls["command"] = command
        Path(command[2]).write_bytes(b"wav-data")
        return SimpleNamespace(returncode=0, stderr="", stdout="")
    monkeypatch.setattr(voiceover.subprocess, "run", fake_run)
    result = voiceover.synthesize_voiceover("one two three four", target_seconds=2)
    assert calls["command"][calls["command"].index("-s") + 1] == "120"
    assert Path(result["file_path"]).is_file()


def test_project_task_without_key_is_idempotent_across_dispatch_retries():
    from app.database import SessionLocal
    from app.models import VideoProject
    from app.services.task_dispatch import dispatch_agent_task

    payload = {
        "topic": "How geothermal energy works",
        "video_format": "shorts",
        "target_seconds": 30,
        "scene_count": 3,
        "confirm_pexels_license": True,
        "use_voiceover": False,
    }
    with SessionLocal() as db:
        first = dispatch_agent_task("project.create", payload, db)
        second = dispatch_agent_task("project.create", payload, db)
        assert first["project_id"] == second["project_id"]
        assert first["project_key"] == second["project_key"]
        db.commit()
    with SessionLocal() as db:
        db.query(VideoProject).filter(VideoProject.project_key == first["project_key"]).delete()
        db.commit()


def test_memora_project_memory_is_opt_in_private_and_idempotent():
    from types import SimpleNamespace
    from uuid import uuid4

    from app.database import SessionLocal
    from app.models import VideoProject
    from app.services import project_pipeline

    project_key = "memora-test-" + uuid4().hex[:12]
    with SessionLocal() as db:
        project = VideoProject(project_key=project_key, topic="Test completed project", video_format="shorts", target_seconds=30, confirm_pexels_license=True, status="completed")
        db.add(project)
        db.commit()
        project_id = project.id
    try:
        monkey_settings = SimpleNamespace(memora_write_enabled=True)
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(project_pipeline, "get_settings", lambda: monkey_settings)
        monkeypatch.setattr(project_pipeline, "configured_peers", lambda: {"memora": object()})
        calls = []
        def fake_post(name, path, payload, **kwargs):
            calls.append((name, path, payload, kwargs))
            return {"id": "memory-test-123"}
        monkeypatch.setattr(project_pipeline, "post_peer_json", fake_post)
        try:
            with SessionLocal() as db:
                result = project_pipeline.sync_project_memory(project_id, db)
                assert result["status"] == "stored"
                assert result["memory_id"] == "memory-test-123"
                stored = db.get(VideoProject, project_id)
                assert stored.memora_memory_status == "stored"
                assert stored.memora_memory_id == "memory-test-123"
            assert calls[0][0:2] == ("memora", "/v1/memories")
            payload = calls[0][2]
            assert payload["target_namespace_path"] == "memora://vyralx/private"
            assert payload["memory_type"] == "episodic"
            assert payload["idempotency_key"].startswith("vyralx-project-")
            assert "agent_id" not in payload
            with SessionLocal() as db:
                replay = project_pipeline.sync_project_memory(project_id, db)
                assert replay["idempotent_replay"] is True
            assert len(calls) == 1
        finally:
            monkeypatch.undo()
    finally:
        with SessionLocal() as db:
            db.query(VideoProject).filter(VideoProject.project_key == project_key).delete()
            db.commit()


def test_memora_context_reads_only_vyralx_private_namespace(monkeypatch):
    from types import SimpleNamespace

    from app.services import project_pipeline

    monkeypatch.setattr(project_pipeline, "get_settings", lambda: SimpleNamespace(memora_read_enabled=True))
    monkeypatch.setattr(project_pipeline, "configured_peers", lambda: {"memora": object()})
    calls = {}
    def fake_get(name, path, params, **kwargs):
        calls["name"], calls["path"], calls["params"] = name, path, params
        return [{"id": "memory-9", "content_text": "A previously completed wind-energy video.", "memory_type": "episodic", "importance": 0.35}]
    monkeypatch.setattr(project_pipeline, "get_peer_json", fake_get)
    context, status = project_pipeline._fetch_memora_context(SimpleNamespace(topic="wind energy", id=9))
    assert status == "used"
    assert context[0]["id"] == "memory-9"
    assert calls["name"] == "memora"
    assert calls["path"] == "/v1/memories/search"
    assert calls["params"]["namespace_path"] == "memora://vyralx/private"
    assert calls["params"]["limit"] == 5
