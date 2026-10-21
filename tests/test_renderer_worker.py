"""Tests for the dedicated background render worker, FFmpeg/MoviePy rendering, and resource bounding."""
from __future__ import annotations

import json
import subprocess
from collections import namedtuple
from unittest.mock import patch

import pytest

from app.database import SessionLocal
from app.models import Asset, RenderJob, Source
from app.services.renderer import (
    PRESETS,
    _posix_resource_limiter,
    _verify_disk_space,
    render_video,
    render_video_with_moviepy,
)
from app.worker import claim_render_job, process_render_job


def test_presets_aspect_ratios():
    assert PRESETS["shorts"] == (1080, 1920)  # 9:16 vertical
    assert PRESETS["long"] == (1920, 1080)    # 16:9 horizontal
    assert PRESETS["square"] == (1080, 1080)  # 1:1 square


def test_posix_resource_limiter():
    limiter = _posix_resource_limiter(max_memory_mb=512, nice_val=10)
    assert callable(limiter)
    # Executing the limiter should not crash even if resource/nice is missing
    limiter()


def test_verify_disk_space_sufficient(tmp_path):
    # Should not raise for normal temporary directory
    _verify_disk_space(tmp_path / "test.mp4")


def test_verify_disk_space_insufficient(tmp_path):
    DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])
    with patch("shutil.disk_usage", return_value=DiskUsage(1000, 500, 100)):  # 100 bytes free
        with pytest.raises(RuntimeError, match="Insufficient disk space"):
            _verify_disk_space(tmp_path / "test.mp4")


def test_render_video_validates_inputs(tmp_path):
    dest = tmp_path / "out.mp4"
    nonexistent = tmp_path / "nonexistent.mp4"

    with pytest.raises(FileNotFoundError, match="Source media not found"):
        render_video(nonexistent, dest, "shorts")

    source = tmp_path / "source.mp4"
    source.write_bytes(b"dummy")

    with pytest.raises(ValueError, match="Unknown render preset"):
        render_video(source, dest, "invalid_preset")

    with pytest.raises(ValueError, match="fit_mode must be pad or crop"):
        render_video(source, dest, "shorts", fit_mode="stretch")

    with pytest.raises(ValueError, match="trim_start_seconds must be non-negative"):
        render_video(source, dest, "shorts", trim_start_seconds=-1)

    with pytest.raises(ValueError, match="trim_end_seconds must be greater"):
        render_video(source, dest, "shorts", trim_start_seconds=10, trim_end_seconds=5)


def test_render_video_ffmpeg_command_and_resource_bounds(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video-data")
    dest = tmp_path / "output.mp4"

    executed_commands = []

    def fake_run(cmd, **kwargs):
        executed_commands.append((cmd, kwargs))
        dest.write_bytes(b"rendered-mp4-data")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out = render_video(
        source,
        dest,
        "shorts",
        fit_mode="crop",
        cpu_threads=2,
        max_memory_mb=256,
        normalize_loudness=True,
    )
    assert out == str(dest)
    assert len(executed_commands) == 1
    cmd, kwargs = executed_commands[0]

    # Verify CPU thread bounding
    assert "-threads" in cmd
    threads_idx = cmd.index("-threads")
    assert cmd[threads_idx + 1] == "2"

    # Verify vertical 9:16 Shorts dimensions
    assert any("crop=1080:1920" in arg for arg in cmd)

    # Verify audio loudness normalization filter is chained
    assert any("loudnorm=I=-14.0" in arg for arg in cmd)


def test_render_video_timeout_cleanup(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video-data")
    dest = tmp_path / "output.mp4"
    dest.write_bytes(b"partial-data")

    def timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=10)

    monkeypatch.setattr(subprocess, "run", timeout_run)

    with pytest.raises(RuntimeError, match="Render exceeded configured time limit"):
        render_video(source, dest, "shorts")
    assert not dest.exists()


def test_render_video_with_moviepy_fallback(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video-data")
    dest = tmp_path / "output.mp4"

    # When MoviePy is not available or mocked as unavailable, it should delegate to render_video
    with patch("app.services.renderer.render_video", return_value=str(dest)) as mock_render:
        res = render_video_with_moviepy(source, dest, "shorts")
        assert res == str(dest)
        mock_render.assert_called_once()


def test_worker_processes_single_asset_render_job(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"source-content")

    # Mock render_video, probe_media, and analyze_media_signals
    out_video = tmp_path / "rendered.mp4"
    out_video.write_bytes(b"rendered-content")

    monkeypatch.setattr("app.worker.render_video", lambda *args, **kwargs: str(out_video))
    monkeypatch.setattr("app.worker.probe_media", lambda *args, **kwargs: {"duration_seconds": 15.0, "width": 1080, "height": 1920, "audio_stream_count": 1})
    monkeypatch.setattr("app.worker.analyze_media_signals", lambda *args, **kwargs: {"status": "analyzed", "audio_metrics": {"integrated_loudness_lufs": -14.2}})

    with SessionLocal() as db:
        source = Source(
            title="Render Test Source",
            platform="manual",
            license_name="Custom Written Permission",
            permission_reference="https://example.com/permission/ref-123",
            rights_verified=True,
        )
        db.add(source)
        db.flush()
        asset = Asset(
            source_id=source.id,
            title="Render Test Asset",
            file_path=str(video),
            rights_verified=True,
        )
        db.add(asset)
        db.flush()
        job = RenderJob(
            asset_id=asset.id,
            preset="shorts",
            status="queued",
            options_json=json.dumps({"target_seconds": 15}),
        )
        db.add(job)
        db.commit()
        job_id = job.id

    claimed = None
    with SessionLocal() as db:
        claimed = claim_render_job(db)
    assert claimed == job_id

    process_render_job(job_id)

    with SessionLocal() as db:
        completed_job = db.get(RenderJob, job_id)
        assert completed_job.status == "completed"
        assert completed_job.output_path == str(out_video)
        opts = json.loads(completed_job.options_json)
        assert "signal_analysis" in opts
        assert opts["signal_analysis"]["status"] == "analyzed"


def test_worker_processes_montage_render_job(tmp_path, monkeypatch):
    clip1 = tmp_path / "clip1.mp4"
    clip2 = tmp_path / "clip2.mp4"
    clip1.write_bytes(b"clip-1")
    clip2.write_bytes(b"clip-2")

    out_montage = tmp_path / "montage.mp4"
    out_montage.write_bytes(b"montage-content")

    monkeypatch.setattr("app.worker.render_montage", lambda *args, **kwargs: str(out_montage))
    monkeypatch.setattr("app.worker.probe_media", lambda *args, **kwargs: {"duration_seconds": 30.0, "width": 1080, "height": 1920, "audio_stream_count": 1})
    monkeypatch.setattr("app.worker.analyze_media_signals", lambda *args, **kwargs: {"status": "analyzed", "audio_metrics": {"integrated_loudness_lufs": -14.0}})

    with SessionLocal() as db:
        src1 = Source(title="Src1", platform="manual", license_name="Custom Written Permission", permission_reference="https://example.com/perm1", rights_verified=True)
        src2 = Source(title="Src2", platform="manual", license_name="Custom Written Permission", permission_reference="https://example.com/perm2", rights_verified=True)
        db.add_all([src1, src2])
        db.flush()

        a1 = Asset(source_id=src1.id, title="A1", file_path=str(clip1), rights_verified=True)
        a2 = Asset(source_id=src2.id, title="A2", file_path=str(clip2), rights_verified=True)
        db.add_all([a1, a2])
        db.flush()

        job = RenderJob(
            asset_id=a1.id,
            preset="shorts",
            status="queued",
            options_json=json.dumps({"montage_asset_ids": [a1.id, a2.id], "target_seconds": 30}),
        )
        db.add(job)
        db.commit()
        job_id = job.id

    with SessionLocal() as db:
        claimed = claim_render_job(db)
    assert claimed == job_id

    process_render_job(job_id)

    with SessionLocal() as db:
        completed = db.get(RenderJob, job_id)
        assert completed.status == "completed"
        assert completed.output_path == str(out_montage)
