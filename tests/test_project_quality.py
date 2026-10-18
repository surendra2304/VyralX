"""Regression tests for persisted topic-to-video QA reports."""
from app.services.project_quality import build_project_quality_report


def test_complete_project_report_is_ready_for_operator_review(tmp_path):
    voice = tmp_path / "voice.wav"
    captions = tmp_path / "captions.srt"
    thumbnail = tmp_path / "thumbnail.jpg"
    voice.write_bytes(b"audio")
    captions.write_text("1\n00:00:00,000 --> 00:00:45,000\nHello world\n", encoding="utf-8")
    thumbnail.write_bytes(b"image")

    report = build_project_quality_report(
        target_seconds=45,
        actual_duration=45.01,
        expected_width=1080,
        expected_height=1920,
        actual_width=1080,
        actual_height=1920,
        audio_stream_count=1,
        voiceover_requested=True,
        voiceover_path=voice,
        subtitle_path=captions,
        subtitle_segments=[{"start_seconds": 0, "end_seconds": 45, "text": "Hello world"}],
        caption_text="Hello world",
        thumbnail_path=thumbnail,
        scene_rights_checks=[True, True, True],
    )

    assert report["status"] == "ready_for_operator_review"
    assert report["warning_count"] == 0
    assert report["automatic_publish_approval"] is False
    assert {item["id"] for item in report["checks"]} >= {
        "duration", "dimensions", "audio_track", "narration_file",
        "caption_coverage", "caption_timing", "thumbnail", "scene_provenance",
    }


def test_quality_report_surfaces_caption_and_source_warnings(tmp_path):
    captions = tmp_path / "captions.srt"
    thumbnail = tmp_path / "thumbnail.jpg"
    captions.write_text("SRT exists", encoding="utf-8")
    thumbnail.write_bytes(b"image")

    report = build_project_quality_report(
        target_seconds=30,
        actual_duration=30,
        expected_width=1080,
        expected_height=1920,
        actual_width=1080,
        actual_height=1920,
        audio_stream_count=0,
        voiceover_requested=True,
        voiceover_path=None,
        subtitle_path=captions,
        subtitle_segments=[{"start_seconds": 1, "end_seconds": 20, "text": "Different words"}],
        caption_text="Expected words",
        thumbnail_path=thumbnail,
        scene_rights_checks=[True, False],
    )

    assert report["status"] == "review_required"
    assert report["warning_count"] >= 4
    checks = {item["id"]: item["status"] for item in report["checks"]}
    assert checks["audio_track"] == "warning"
    assert checks["narration_file"] == "warning"
    assert checks["caption_coverage"] == "warning"
    assert checks["caption_timing"] == "warning"
    assert checks["scene_provenance"] == "warning"
