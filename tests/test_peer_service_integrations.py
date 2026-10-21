"""Integration tests for Peer Services (Inference, Sentinel, IntelX) and Safety Invariants 2 & 3."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.database import SessionLocal
from app.models import Asset, ContentPack, PublishJob, RenderJob, Source
from app.services.content import generate_content_pack
from app.services.rights import source_is_publishable
from app.services.sentinel import verify_render_publish_policy
from app.services.task_dispatch import dispatch_agent_task
from app.worker import process_publish_job


def _make_dummy_media(tmp_path: Path, filename: str = "render.mp4", size: int = 1024) -> Path:
    path = tmp_path / filename
    path.write_bytes(b"M" * size)
    return path


def test_inference_universal_task_envelope_and_generation(monkeypatch: pytest.MonkeyPatch):
    settings_obj = SimpleNamespace(
        inference_url="http://inference:8000",
        inference_api_key="friday-secret-inference-key",
        inference_generation_path="/v1/task/execute",
        inference_timeout_seconds=10,
        inference_model="",
        channel_name="FRIDAY Tech",
        channel_niche="Artificial Intelligence",
        channel_content_pillars="AI, Robotics, Automation",
        channel_avoid_topics="Politics, Gossip",
        channel_brand_voice="Authoritative yet accessible",
        channel_call_to_action="Subscribe to FRIDAY Tech",
        channel_language="English",
    )
    monkeypatch.setattr("app.services.content.get_settings", lambda: settings_obj)
    monkeypatch.setattr("app.config.get_settings", lambda: settings_obj)

    captured_request = {}

    valid_inference_response = {
        "hook": "What if AI could edit videos in seconds?",
        "script": "Artificial intelligence is changing media synthesis forever. From automated scripting to vertical rendering, the pipeline never sleeps.",
        "scene_plan": [
            {"timecode": "00:00-00:03", "visual": "Futuristic server room with neon lights", "on_screen_text": "Autonomous Media Synthesis"},
            {"timecode": "00:03-00:06", "visual": "Fast-paced video editing interface rendering frames", "on_screen_text": "Instant 9:16 Shorts"},
        ],
        "voiceover": "Artificial intelligence is changing media synthesis forever. From automated scripting to vertical rendering, the pipeline never sleeps.",
        "caption": "What if AI could edit videos in seconds? The pipeline never sleeps.",
        "title_options": [
            "How AI Automates Video Synthesis",
            "Inside the FRIDAY Autonomous Pipeline",
        ],
        "description": "Discover how VyralX autonomously synthesizes vertical video content inside the FRIDAY Universe.",
        "tags": ["AI", "Automation", "VideoEditing", "FRIDAY"],
        "thumbnail_brief": "Glowing holographic timeline with futuristic FRIDAY branding.",
        "fact_check_notes": ["Verify rendering speeds and pipeline throughput."],
        "rights_notes": "Use only verified stock footage from authorized providers.",
    }

    class MockHttpxResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "task_id": "inference-res-123",
                "status": "SUCCESS",
                "result": {
                    "response": json.dumps(valid_inference_response),
                },
            }

    def mock_post(url, **kwargs):
        captured_request["url"] = url
        captured_request["headers"] = kwargs.get("headers")
        captured_request["json"] = kwargs.get("json")
        return MockHttpxResponse()

    monkeypatch.setattr("app.services.content.httpx.post", mock_post)

    result = generate_content_pack(
        "Autonomous Video Synthesis",
        video_format="shorts",
        audience="Tech Creators",
        tone="Energetic and informative",
        target_seconds=45,
    )

    # Verify Universal Envelope
    assert captured_request["url"] == "http://inference:8000/v1/task/execute"
    headers = captured_request["headers"]
    assert headers["Authorization"] == "Bearer friday-secret-inference-key"
    assert headers["X-FRIDAY-API-Key"] == "friday-secret-inference-key"
    assert headers["X-API-Key"] == "friday-secret-inference-key"

    envelope = captured_request["json"]
    assert envelope["source_agent"] == "vyralx"
    assert envelope["target_agent"] == "inference"
    assert envelope["action"] == "vyralx.content.generate"
    assert envelope["priority"] == "normal"
    assert "Autonomous Video Synthesis" in envelope["payload"]["context"]["topic"]
    assert envelope["payload"]["context"]["channel_strategy"]["channel_name"] == "FRIDAY Tech"

    # Verify parsed content pack
    assert result["hook"] == "What if AI could edit videos in seconds?"
    assert len(result["scene_plan"]) == 2
    assert result["title_options"][0] == "How AI Automates Video Synthesis"
    assert "AI" in result["tags"]


def test_inference_dispatch_agent_task_persistence(monkeypatch: pytest.MonkeyPatch):
    settings_obj = SimpleNamespace(
        inference_url="http://inference:8000",
        inference_api_key="test-key",
        inference_generation_path="/v1/task/execute",
        inference_timeout_seconds=10,
        inference_model="",
        channel_name="",
        channel_niche="",
        channel_content_pillars="",
        channel_avoid_topics="",
        channel_brand_voice="",
        channel_call_to_action="",
        channel_language="English",
    )
    monkeypatch.setattr("app.services.content.get_settings", lambda: settings_obj)
    monkeypatch.setattr("app.config.get_settings", lambda: settings_obj)
    monkeypatch.setattr("app.services.task_dispatch.get_settings", lambda: settings_obj)
    monkeypatch.setattr("app.config.get_settings", lambda: settings_obj)

    pack_data = {
        "hook": "Hook text",
        "script": "Spoken script",
        "scene_plan": [{"visual": "Scene 1"}],
        "voiceover": "Voice narration",
        "caption": "Captions",
        "title_options": ["Title One"],
        "description": "Desc",
        "tags": ["tag1"],
        "thumbnail_brief": "Thumbnail art",
        "fact_check_notes": [],
    }

    class MockHttpxResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "SUCCESS", "result": {"response": json.dumps(pack_data)}}

    monkeypatch.setattr("app.services.content.httpx.post", lambda *a, **kw: MockHttpxResponse())

    with SessionLocal() as db:
        res = dispatch_agent_task(
            "content.generate",
            {"topic": "Quantum Computing", "video_format": "shorts"},
            db,
        )
        content_id = res["content_pack_id"]
        record = db.get(ContentPack, content_id)
        assert record is not None
        assert record.topic == "Quantum Computing"
        assert record.video_format == "shorts"
        assert record.status == "generated"

        # Cleanup
        db.delete(record)
        db.commit()


def test_sentinel_pre_publish_policy_audit_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    render_file = _make_dummy_media(tmp_path, "final_render.mp4", size=5000)
    settings_obj = SimpleNamespace(
        sentinel_required_for_publish=True,
        sentinel_policy_path="/v1/security/audit",
        ffmpeg_bin="ffmpeg",
        render_audio_loudness_target_lufs=-14.0,
        render_audio_loudness_min_lufs=-24.0,
        render_audio_loudness_max_lufs=-10.0,
    )
    monkeypatch.setattr("app.services.sentinel.get_settings", lambda: settings_obj)
    monkeypatch.setattr("app.services.sentinel.configured_peers", lambda: {"sentinel"})

    # Mock probe and signal analysis
    monkeypatch.setattr("app.services.sentinel.probe_media", lambda path: {
        "duration_seconds": 30.0,
        "width": 1080,
        "height": 1920,
        "audio_stream_count": 1,
    })

    signal_scan = {
        "status": "analyzed",
        "audio_metrics": {
            "integrated_loudness_lufs": -14.1,
            "loudness_range_lu": 4.5,
        },
        "black_intervals": [],
        "silence_intervals": [],
    }

    dispatched_payload = {}

    def mock_post_peer_json(peer_name, path, payload):
        assert peer_name == "sentinel"
        assert path == "/v1/security/audit"
        dispatched_payload.update(payload)
        return {
            "allowed": True,
            "decision": "allow",
            "reason": "All media assets and loudness levels compliant with publishing policy",
        }

    monkeypatch.setattr("app.services.sentinel.post_peer_json", mock_post_peer_json)

    source_asset = SimpleNamespace(id=101, rights_verified=True)
    source_record = SimpleNamespace(
        id=202,
        title="Stock Footage",
        platform="pexels",
        license_name="Pexels Content License",
        rights_verified=True,
    )

    decision = verify_render_publish_policy(
        job_id=1,
        asset_id=101,
        render_job_id=5,
        title="Verified AI Short",
        description="Clean video description",
        privacy_status="private",
        render_path=render_file,
        signal_analysis=signal_scan,
        render_sources=[(source_asset, source_record)],
    )

    assert decision["allowed"] is True
    assert decision["decision"] == "allow"

    # Verify audit payload dispatched to Sentinel
    assert dispatched_payload["action"] == "youtube.publish"
    assert dispatched_payload["scope_policy"] == "vyralx-publish-policy-v1"
    assert dispatched_payload["rights_verified"] is True
    meta = dispatched_payload["media_metadata"]
    assert meta["duration_seconds"] == 30.0
    assert meta["width"] == 1080
    assert meta["height"] == 1920
    assert len(meta["sha256"]) == 64

    qscan = dispatched_payload["quality_scan"]
    assert qscan["integrated_loudness_lufs"] == -14.1
    assert qscan["loudness_pass"] is True
    assert qscan["black_frames_pass"] is True
    assert qscan["silence_gaps_pass"] is True
    assert qscan["overall_quality_pass"] is True

    sources = dispatched_payload["sources"]
    assert len(sources) == 1
    assert sources[0]["platform"] == "pexels"
    assert sources[0]["rights_verified"] is True


def test_sentinel_audit_fail_closed_on_denial_and_unreachable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    render_file = _make_dummy_media(tmp_path, "render_test.mp4", size=2048)
    settings_obj = SimpleNamespace(
        sentinel_required_for_publish=True,
        sentinel_policy_path="/v1/security/audit",
        ffmpeg_bin="ffmpeg",
        render_audio_loudness_target_lufs=-14.0,
        render_audio_loudness_min_lufs=-24.0,
        render_audio_loudness_max_lufs=-10.0,
    )
    monkeypatch.setattr("app.services.sentinel.get_settings", lambda: settings_obj)

    monkeypatch.setattr("app.services.sentinel.probe_media", lambda p: {
        "duration_seconds": 15.0,
        "width": 1080,
        "height": 1920,
        "audio_stream_count": 1,
    })

    signal_scan = {
        "status": "analyzed",
        "audio_metrics": {"integrated_loudness_lufs": -14.0},
        "black_intervals": [],
        "silence_intervals": [],
    }

    # Case 1: Sentinel peer is configured but explicitly denies publishing
    monkeypatch.setattr("app.services.sentinel.configured_peers", lambda: {"sentinel"})
    monkeypatch.setattr("app.services.sentinel.post_peer_json", lambda *a, **kw: {
        "allowed": False,
        "decision": "deny",
        "reason": "Security risk: unreviewed third-party audio stem detected",
    })

    with pytest.raises(RuntimeError, match="Sentinel pre-publish policy verification denied"):
        verify_render_publish_policy(
            job_id=2, asset_id=20, render_job_id=10,
            title="Denied Video", render_path=render_file, signal_analysis=signal_scan,
        )

    # Case 2: Sentinel is unreachable when required -> fail closed
    def mock_unreachable(*a, **kw):
        raise ConnectionError("Host sentinel:8000 unreachable")

    monkeypatch.setattr("app.services.sentinel.post_peer_json", mock_unreachable)

    with pytest.raises(RuntimeError, match="Sentinel pre-publish audit failed unreachable"):
        verify_render_publish_policy(
            job_id=2, asset_id=20, render_job_id=10,
            title="Unreachable Peer Video", render_path=render_file, signal_analysis=signal_scan,
        )

    # Case 3: Sentinel is required but not configured in mesh -> fail closed
    monkeypatch.setattr("app.services.sentinel.configured_peers", lambda: set())
    with pytest.raises(RuntimeError, match="Sentinel audit is required for publication but Sentinel peer is not configured"):
        verify_render_publish_policy(
            job_id=2, asset_id=20, render_job_id=10,
            title="Unconfigured Peer Video", render_path=render_file, signal_analysis=signal_scan,
        )


def test_safety_invariant_2_media_rights_verification_gate(tmp_path: Path):
    """Safety Invariant 2: Stock media from Pexels requires verified license confirmation and FFprobe inspection.
    Unverified assets cannot be included in final renders or published.
    """
    # 1. Unverified Pexels asset without valid license is not publishable
    invalid_pexels_source = Source(
        title="Unverified Pexels Clip",
        platform="pexels",
        source_url="https://www.pexels.com/video/12345/",
        license_name="unknown",
        permission_reference="",
        rights_verified=False,
    )
    assert not source_is_publishable(invalid_pexels_source)

    # 2. Pexels with forged external domain is rejected
    forged_pexels_source = Source(
        title="Forged Pexels Clip",
        platform="pexels",
        source_url="https://pirate-media.invalid/video/12345/",
        license_name="Pexels Content License",
        permission_reference="https://www.pexels.com/license/",
        rights_verified=True,
    )
    assert not source_is_publishable(forged_pexels_source)

    # 3. Verified Pexels source with official URL and license is accepted
    valid_pexels_source = Source(
        title="Official Pexels Clip",
        platform="pexels",
        source_url="https://www.pexels.com/video/99999/",
        license_name="Pexels Content License",
        permission_reference="https://www.pexels.com/license/",
        rights_verified=True,
    )
    assert source_is_publishable(valid_pexels_source)

    # 4. Attempting to publish an unverified asset fails inside worker
    video = _make_dummy_media(tmp_path, "unverified_rights.mp4")

    with SessionLocal() as db:
        source = Source(
            title="Unverified Source",
            platform="manual",
            license_name="",
            permission_reference="",
            rights_verified=False,
        )
        db.add(source)
        db.flush()

        asset = Asset(
            source_id=source.id,
            title="Unverified Asset",
            file_path=str(video),
            rights_verified=False,
        )
        db.add(asset)
        db.flush()

        render = RenderJob(
            asset_id=asset.id,
            preset="shorts",
            status="completed",
            output_path=str(video),
            options_json="{}",
        )
        db.add(render)
        db.flush()

        publish = PublishJob(
            asset_id=asset.id,
            render_job_id=render.id,
            title="Unverified Publish Job",
            status="queued",
            privacy_status="private",
            tags_json="[]",
            approved_at=datetime.now(timezone.utc),
        )
        db.add(publish)
        db.commit()

        job_id = publish.id

    try:
        process_publish_job(job_id)

        with SessionLocal() as db:
            refreshed = db.get(PublishJob, job_id)
            assert refreshed is not None
            assert refreshed.status == "failed"
            assert "Verified source license/permission record is required" in refreshed.error
    finally:
        with SessionLocal() as db:
            p = db.get(PublishJob, job_id)
            if p:
                r = db.get(RenderJob, p.render_job_id)
                a = db.get(Asset, p.asset_id)
                s = db.get(Source, a.source_id) if a and a.source_id else None
                db.delete(p)
                if r:
                    db.delete(r)
                if a:
                    db.delete(a)
                if s:
                    db.delete(s)
                db.commit()


def test_safety_invariant_3_audio_loudness_and_black_frame_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Safety Invariant 3: Video renders must pass audio loudness scanning (-14 LUFS standard)
    and black-frame/silence gap detection before publication.
    """
    video = _make_dummy_media(tmp_path, "qa_test.mp4")
    token_file = tmp_path / "secrets" / "token.json"
    settings_obj = SimpleNamespace(
        youtube_token_file=token_file,
        youtube_upload_enabled=True,
        sentinel_required_for_publish=False,
        sentinel_policy_path="/v1/security/audit",
        ffmpeg_bin="ffmpeg",
        youtube_category_id="22",
        render_audio_loudness_target_lufs=-14.0,
        render_audio_loudness_min_lufs=-24.0,
        render_audio_loudness_max_lufs=-10.0,
    )
    monkeypatch.setattr("app.worker.get_settings", lambda: settings_obj)

    with SessionLocal() as db:
        source = Source(
            title="QA Test Source",
            platform="manual",
            license_name="Standard License",
            permission_reference="QA-REF-001",
            rights_verified=True,
        )
        db.add(source)
        db.flush()

        asset = Asset(
            source_id=source.id,
            title="QA Test Asset",
            file_path=str(video),
            rights_verified=True,
        )
        db.add(asset)
        db.flush()

        render = RenderJob(
            asset_id=asset.id,
            preset="shorts",
            status="completed",
            output_path=str(video),
            options_json="{}",
        )
        db.add(render)
        db.flush()

        publish = PublishJob(
            asset_id=asset.id,
            render_job_id=render.id,
            title="QA Publish Job",
            description="QA Description",
            status="uploading",
            attempts=1,
            privacy_status="private",
            tags_json="[]",
            approved_at=datetime.now(timezone.utc),
        )
        db.add(publish)
        db.commit()

        job_id = publish.id

    try:
        # Mock probe_media to simulate valid media with audio stream
        monkeypatch.setattr("app.worker.probe_media", lambda path: {
            "duration_seconds": 30.0,
            "audio_stream_count": 1,
            "width": 1080,
            "height": 1920,
        })

        # Test 1: Black frame detection violation
        black_frame_signal = {
            "status": "analyzed",
            "audio_metrics": {"integrated_loudness_lufs": -14.0},
            "black_intervals": [{"start_seconds": 5.0, "end_seconds": 6.5, "duration_seconds": 1.5}],
            "silence_intervals": [],
        }
        monkeypatch.setattr("app.worker.analyze_media_signals", lambda *a, **kw: black_frame_signal)

        process_publish_job(job_id)
        with SessionLocal() as db:
            refreshed = db.get(PublishJob, job_id)
            assert refreshed.status == "failed"
            assert "Safety Invariant 3 violation: 1 black-frame intervals detected" in refreshed.error

        # Test 2: Audio loudness violation (too quiet: -32 LUFS < -24 LUFS min)
        with SessionLocal() as db:
            refreshed = db.get(PublishJob, job_id)
            refreshed.status = "uploading"
            refreshed.error = ""
            db.commit()

        loudness_fail_signal = {
            "status": "analyzed",
            "audio_metrics": {"integrated_loudness_lufs": -32.5},
            "black_intervals": [],
            "silence_intervals": [],
        }
        monkeypatch.setattr("app.worker.analyze_media_signals", lambda *a, **kw: loudness_fail_signal)

        process_publish_job(job_id)
        with SessionLocal() as db:
            refreshed = db.get(PublishJob, job_id)
            assert refreshed.status == "failed"
            assert "Audio loudness (-32.5 LUFS) is outside acceptable limits" in refreshed.error

        # Test 3: Long silence gap violation
        with SessionLocal() as db:
            refreshed = db.get(PublishJob, job_id)
            refreshed.status = "uploading"
            refreshed.error = ""
            db.commit()

        silence_fail_signal = {
            "status": "analyzed",
            "audio_metrics": {"integrated_loudness_lufs": -14.0},
            "black_intervals": [],
            "silence_intervals": [{"start_seconds": 10.0, "end_seconds": 15.0, "duration_seconds": 5.0}],
        }
        monkeypatch.setattr("app.worker.analyze_media_signals", lambda *a, **kw: silence_fail_signal)

        process_publish_job(job_id)
        with SessionLocal() as db:
            refreshed = db.get(PublishJob, job_id)
            assert refreshed.status == "failed"
            assert "long silence gaps detected" in refreshed.error

    finally:
        with SessionLocal() as db:
            p = db.get(PublishJob, job_id)
            if p:
                r = db.get(RenderJob, p.render_job_id)
                a = db.get(Asset, p.asset_id)
                s = db.get(Source, a.source_id) if a and a.source_id else None
                db.delete(p)
                if r:
                    db.delete(r)
                if a:
                    db.delete(a)
                if s:
                    db.delete(s)
                db.commit()
