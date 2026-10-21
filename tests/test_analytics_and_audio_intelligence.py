"""Tests for YouTube audience analytics intelligence, performance tiers, Memora feedback, and dynamic BGM synthesis."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models import PublishJob, VideoMetric
from app.services.audio_mixer import select_bgm_track_for_tone, synthesize_ambient_pad_bgm
from app.services.youtube_analytics import (
    calculate_engagement_rate,
    classify_performance_tier,
    extract_top_performing_topics,
    record_feedback_to_memora,
    sync_video_metrics_batch,
)


def test_calculate_engagement_rate():
    assert calculate_engagement_rate(0, 10, 5) == 0.0
    assert calculate_engagement_rate(1000, 50, 10) == 6.0
    assert calculate_engagement_rate(200, 10, 0) == 5.0
    # Clamped to 100%
    assert calculate_engagement_rate(10, 500, 500) == 100.0


def test_classify_performance_tier():
    # Breakout (> 10000 views or > 2000 views with >= 10% engagement)
    assert classify_performance_tier(15000, 100, 10) == "breakout"
    assert classify_performance_tier(2500, 300, 50) == "breakout"

    # Strong (> 2000 views or >= 6% engagement)
    assert classify_performance_tier(3000, 50, 10) == "strong"
    assert classify_performance_tier(800, 60, 10) == "strong"

    # Healthy (> 500 views or >= 3% engagement)
    assert classify_performance_tier(600, 10, 2) == "healthy"
    assert classify_performance_tier(300, 12, 0) == "healthy"

    # Underperforming
    assert classify_performance_tier(100, 1, 0) == "underperforming"


def test_extract_top_performing_topics():
    records = [
        {"title": "Quantum Breakthrough", "engagement_rate": 8.5},
        {"title": "Boring Video", "engagement_rate": 1.2},
        {"title": "AI Revolution", "engagement_rate": 5.4},
        {"title": "Quantum Breakthrough", "engagement_rate": 8.5},  # duplicate
    ]
    top = extract_top_performing_topics(records, threshold_engagement=5.0)
    assert len(top) == 2
    assert "AI Revolution" in top
    assert "Quantum Breakthrough" in top


def test_sync_video_metrics_batch(tmp_path):
    mock_db = next(get_db())
    try:
        # Create a mock publish job
        pub = PublishJob(
            asset_id=1,
            render_job_id=1,
            title="Test Video Title",
            youtube_video_id="vid_sync_test_123",
            status="published",
        )
        mock_db.add(pub)
        mock_db.commit()

        fake_metrics = [
            {
                "youtube_video_id": "vid_sync_test_123",
                "title": "Test Video Title",
                "view_count": 4500,
                "like_count": 320,
                "comment_count": 45,
                "engagement_rate": 8.11,
                "performance_tier": "strong",
            }
        ]

        with patch("app.services.youtube_analytics.fetch_video_metrics", return_value=fake_metrics):
            res = sync_video_metrics_batch(mock_db, ["vid_sync_test_123"])
            assert res["status"] == "synced"
            assert res["synced_count"] == 1

            # Verify persisted row
            row = mock_db.scalar(select(VideoMetric).where(VideoMetric.youtube_video_id == "vid_sync_test_123"))
            assert row is not None
            assert row.view_count == 4500
            assert row.like_count == 320

            # Second sync updates existing row
            fake_metrics[0]["view_count"] = 5200
            res2 = sync_video_metrics_batch(mock_db, ["vid_sync_test_123"])
            assert res2["synced_count"] == 1
            mock_db.refresh(row)
            assert row.view_count == 5200
    finally:
        mock_db.close()


def test_record_feedback_to_memora():
    # When memora is not configured
    with patch("app.services.youtube_analytics.configured_peers", return_value={}):
        res = record_feedback_to_memora(1, "vid_123", "Title", {"view_count": 100})
        assert res["status"] == "skipped"

    # When memora is configured
    with patch("app.services.youtube_analytics.configured_peers", return_value={"memora": True}):
        with patch("app.services.youtube_analytics.post_peer_json", return_value={"id": "mem-456"}):
            stats = {"view_count": 15000, "like_count": 1200, "comment_count": 250}
            res = record_feedback_to_memora(42, "vid_123", "Breakout Title", stats)
            assert res["status"] == "recorded"
            assert res["memory_id"] == "mem-456"
            assert res["tier"] == "breakout"

        # When peer call fails
        with patch("app.services.youtube_analytics.post_peer_json", side_effect=RuntimeError("Memora timeout")):
            res = record_feedback_to_memora(42, "vid_123", "Breakout Title", stats)
            assert res["status"] == "failed"
            assert "Memora timeout" in res["error"]


def test_select_bgm_track_for_tone(tmp_path):
    # Non-existent dir returns None
    assert select_bgm_track_for_tone("energetic", tmp_path / "non_existent") is None

    # Empty dir returns None
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    assert select_bgm_track_for_tone("energetic", music_dir) is None

    # Matching mood filename
    track_energy = music_dir / "track_high_energy_pulse.mp3"
    track_energy.write_bytes(b"mock mp3 data")

    track_ambient = music_dir / "track_ambient_explainer_pad.mp3"
    track_ambient.write_bytes(b"mock mp3 data")

    assert select_bgm_track_for_tone("energetic", music_dir) == track_energy
    assert select_bgm_track_for_tone("calm and factual", music_dir) == track_ambient


def test_synthesize_ambient_pad_bgm(tmp_path):
    out_file = tmp_path / "ambient_test.aac"

    # Test with mocked successful subprocess
    def fake_subprocess_run(cmd, stdout=None, stderr=None, text=True):
        out_file.write_bytes(b"synthesized audio payload")
        return MagicMock(returncode=0, stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        res = synthesize_ambient_pad_bgm(out_file, duration_seconds=2.0, mood="cyber_futuristic")
        assert res == out_file
        assert out_file.is_file()
        assert out_file.stat().st_size > 0

    # Test failure exit code raises RuntimeError
    with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="encoder error")):
        with pytest.raises(RuntimeError, match="FFmpeg ambient audio synthesis failed"):
            synthesize_ambient_pad_bgm(tmp_path / "fail.aac", duration_seconds=2.0)

    # Test FileNotFoundError fallback
    with patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
        fallback_file = tmp_path / "fallback.aac"
        res_fallback = synthesize_ambient_pad_bgm(fallback_file, duration_seconds=2.0)
        assert res_fallback == fallback_file
        assert fallback_file.is_file()
        assert fallback_file.stat().st_size > 0


def test_api_analytics_and_audio_routes(tmp_path):
    settings = get_settings()
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    # 1. POST /api/analytics/sync
    fake_metrics = [
        {
            "youtube_video_id": "vid_api_test_99",
            "title": "API Test Video",
            "view_count": 12000,
            "like_count": 900,
            "comment_count": 120,
            "engagement_rate": 8.5,
            "performance_tier": "breakout",
        }
    ]
    with patch("app.services.youtube_analytics.fetch_video_metrics", return_value=fake_metrics):
        with patch("app.services.youtube_analytics.configured_peers", return_value={}):
            resp = client.post(
                "/api/analytics/sync",
                json={"video_ids": ["vid_api_test_99"]},
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "synced"
            assert data["synced_count"] == 1

    # 2. GET /api/analytics/summary
    summary_resp = client.get("/api/analytics/summary", headers=headers)
    assert summary_resp.status_code == 200
    s_data = summary_resp.json()
    assert "total_videos_tracked" in s_data
    assert "cohorts" in s_data
    assert s_data["cohorts"]["breakout"] >= 1

    # 3. POST /api/audio/synthesize-ambient
    with patch("app.services.audio_mixer.subprocess.run") as mock_run:
        # Let fallback or fake write happen
        mock_run.side_effect = FileNotFoundError()
        audio_resp = client.post(
            "/api/audio/synthesize-ambient",
            json={"duration_seconds": 1.5, "mood": "ambient_explainer"},
            headers=headers,
        )
        assert audio_resp.status_code == 200
        a_data = audio_resp.json()
        assert a_data["status"] == "synthesized"
        assert Path(a_data["file_path"]).is_file()
