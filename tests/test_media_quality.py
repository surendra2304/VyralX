from __future__ import annotations

import subprocess
from types import SimpleNamespace

from app.services import media_quality


def test_signal_analyzer_parses_black_frames_and_closed_and_trailing_silence(tmp_path, monkeypatch):
    rendered = tmp_path / "render.mp4"
    rendered.write_bytes(b"fake media bytes")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stderr=(
                "[blackdetect @ 0x1] black_start:3.000000 black_end:4.250000 black_duration:1.250000\n"
                "[silencedetect @ 0x2] silence_start: 11.200000\n"
                "[silencedetect @ 0x2] silence_end: 14.400000 | silence_duration: 3.200000\n"
                "[silencedetect @ 0x2] silence_start: 59.000000\n"
                "[Parsed_ebur128_2 @ 0x3] I: -16.0 LUFS\n"
                "[Parsed_ebur128_2 @ 0x3] Peak: -1.2 dBFS\n"
                "[Parsed_astats_1 @ 0x4] Number of samples clipped: 0\n"
            ),
        )

    monkeypatch.setattr(media_quality.subprocess, "run", fake_run)
    result = media_quality.analyze_media_signals(
        rendered,
        ffmpeg_bin="ffmpeg-test",
        actual_duration=60,
        audio_stream_count=1,
        timeout_seconds=90,
    )

    assert result["status"] == "analyzed"
    assert result["audio_analyzed"] is True
    assert result["audio_metrics"] == {
        "status": "analyzed",
        "integrated_loudness_lufs": -16.0,
        "true_peak_dbfs": -1.2,
        "clipped_samples": 0,
    }
    assert result["black_intervals"] == [
        {"start_seconds": 3.0, "end_seconds": 4.25, "duration_seconds": 1.25}
    ]
    assert result["silence_intervals"] == [
        {"start_seconds": 11.2, "end_seconds": 14.4, "duration_seconds": 3.2},
        {"start_seconds": 59.0, "end_seconds": 60.0, "duration_seconds": 1.0},
    ]
    assert captured["command"][0] == "ffmpeg-test"
    assert "-vf" in captured["command"] and "blackdetect=" in captured["command"][captured["command"].index("-vf") + 1]
    assert "-af" in captured["command"] and "silencedetect=" in captured["command"][captured["command"].index("-af") + 1]
    audio_filter = captured["command"][captured["command"].index("-af") + 1]
    assert "astats=" in audio_filter and "ebur128=" in audio_filter
    assert captured["kwargs"]["timeout"] == 90
    assert captured["kwargs"]["check"] is False


def test_signal_analyzer_skips_audio_filter_when_render_has_no_audio(tmp_path, monkeypatch):
    rendered = tmp_path / "silent.mp4"
    rendered.write_bytes(b"fake media bytes")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(media_quality.subprocess, "run", fake_run)
    result = media_quality.analyze_media_signals(
        rendered,
        actual_duration=30,
        audio_stream_count=0,
    )

    assert result["status"] == "analyzed"
    assert result["audio_analyzed"] is False
    assert result["audio_metrics"]["status"] == "not_applicable"
    assert result["silence_intervals"] == []
    assert "-vf" in captured["command"]
    assert "-af" not in captured["command"]


def test_signal_analyzer_reports_timeout_or_ffmpeg_failure_as_unavailable(tmp_path, monkeypatch):
    rendered = tmp_path / "render.mp4"
    rendered.write_bytes(b"fake media bytes")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(media_quality.subprocess, "run", timeout)
    timed_out = media_quality.analyze_media_signals(
        rendered, actual_duration=10, audio_stream_count=1, timeout_seconds=1
    )
    assert timed_out["status"] == "unavailable"
    assert timed_out["error_type"] == "timeout"

    monkeypatch.setattr(
        media_quality.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="provider path and logs are not exposed"),
    )
    failed = media_quality.analyze_media_signals(rendered, actual_duration=10, audio_stream_count=1)
    assert failed["status"] == "unavailable"
    assert failed["error_type"] == "ffmpeg_exit"
    assert "stderr" not in failed


def test_signal_analyzer_handles_missing_files_and_invalid_durations(tmp_path, monkeypatch):
    missing = media_quality.analyze_media_signals(
        tmp_path / "missing.mp4", actual_duration=10, audio_stream_count=0
    )
    assert missing["status"] == "unavailable"
    assert missing["error_type"] == "missing_output"

    rendered = tmp_path / "render.mp4"
    rendered.write_bytes(b"fake media bytes")
    invalid = media_quality.analyze_media_signals(
        rendered, actual_duration=float("nan"), audio_stream_count=0
    )
    assert invalid["status"] == "unavailable"
    assert invalid["error_type"] == "invalid_duration"



def test_audio_metrics_remain_partial_when_ffmpeg_omits_a_measurement():
    metrics = media_quality._parse_audio_metrics(
        "[Parsed_ebur128_2] I: -18.0 LUFS\n"
        "[Parsed_ebur128_2] Peak: -0.5 dBFS\n"
    )

    assert metrics == {
        "status": "partial",
        "integrated_loudness_lufs": -18.0,
        "true_peak_dbfs": -0.5,
        "clipped_samples": None,
    }
