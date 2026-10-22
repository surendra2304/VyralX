"""Tests for styled Advanced SubStation Alpha (.ass) subtitle engine."""

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import VideoProject
from app.services.captions import _ass_timestamp, write_ass


def test_ass_timestamp_conversion():
    assert _ass_timestamp(0.0) == "0:00:00.00"
    assert _ass_timestamp(1.25) == "0:00:01.25"
    assert _ass_timestamp(65.789) == "0:01:05.79"
    assert _ass_timestamp(3661.05) == "1:01:01.05"


def test_write_ass_valid_segments(tmp_path):
    target = tmp_path / "captions.ass"
    segments = [
        {"start_seconds": 0.0, "end_seconds": 2.5, "text": "Welcome to VyralX video studio."},
        {"start_seconds": 2.5, "end_seconds": 5.0, "text": "Autonomous multi-agent video synthesis."},
    ]
    result = write_ass(segments, target, style="ViralYellow")
    assert result == target
    content = target.read_text(encoding="utf-8")
    assert "[Script Info]" in content
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert "[V4+ Styles]" in content
    assert "ViralYellow" in content
    assert "[Events]" in content
    assert "Dialogue: 0,0:00:00.00,0:00:02.50,ViralYellow,,0,0,0,,Welcome to VyralX video studio." in content
    assert "Dialogue: 0,0:00:02.50,0:00:05.00,ViralYellow,,0,0,0,,Autonomous multi-agent video synthesis." in content


def test_write_ass_with_keyword_highlighting(tmp_path):
    target = tmp_path / "highlighted.ass"
    segments = [
        {"start_seconds": 1.0, "end_seconds": 3.0, "text": "Discover the secret to viral videos!"},
    ]
    write_ass(segments, target, style="CyberNeon", highlight_keywords=["secret", "viral"])
    content = target.read_text(encoding="utf-8")
    assert "{\\c&H0000FFFF&}secret{\\r}" in content
    assert "{\\c&H0000FFFF&}viral{\\r}" in content


def test_write_ass_validation_failures(tmp_path):
    target = tmp_path / "invalid.ass"

    # Non-numeric timestamps
    with pytest.raises(ValueError, match="numeric start and end times"):
        write_ass([{"start_seconds": "invalid", "end_seconds": 2.0, "text": "Bad"}], target)

    # Negative start
    with pytest.raises(ValueError, match="finite positive time range"):
        write_ass([{"start_seconds": -1.0, "end_seconds": 2.0, "text": "Negative"}], target)

    # End <= start
    with pytest.raises(ValueError, match="finite positive time range"):
        write_ass([{"start_seconds": 2.0, "end_seconds": 2.0, "text": "Zero duration"}], target)

    # Empty text
    with pytest.raises(ValueError, match="finite positive time range"):
        write_ass([{"start_seconds": 0.0, "end_seconds": 2.0, "text": "   "}], target)

    # Unordered segments
    with pytest.raises(ValueError, match="ordered by start time"):
        write_ass([
            {"start_seconds": 3.0, "end_seconds": 5.0, "text": "Second"},
            {"start_seconds": 1.0, "end_seconds": 2.0, "text": "First"},
        ], target)

    # Overlapping segments
    with pytest.raises(ValueError, match="must not overlap"):
        write_ass([
            {"start_seconds": 1.0, "end_seconds": 3.0, "text": "First"},
            {"start_seconds": 2.5, "end_seconds": 4.0, "text": "Overlap"},
        ], target)


def test_download_project_ass_captions_endpoint(tmp_path, monkeypatch):
    import uuid
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.prepare_directories()
    Base.metadata.create_all(bind=engine)

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    # 404 for missing project
    resp = client.get("/api/projects/99999/captions.ass", headers=headers)
    assert resp.status_code == 404

    # Create dummy completed project in db
    unique_key = f"test-ass-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        project = VideoProject(
            project_key=unique_key,
            topic="ASS Captions Test",
            video_format="shorts",
            target_seconds=30,
            status="completed",
            attempts=1,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        project_id = project.id

    # Caption file missing -> 404
    resp = client.get(f"/api/projects/{project_id}/captions.ass", headers=headers)
    assert resp.status_code == 404

    # Write ASS caption file into expected path
    ass_dir = settings.data_dir / "subtitles"
    ass_dir.mkdir(parents=True, exist_ok=True)
    ass_file = ass_dir / f"project-{project_id}-attempt-1.ass"
    write_ass([{"start_seconds": 0.0, "end_seconds": 2.0, "text": "Test Caption"}], ass_file)

    # Now endpoint returns 200 and valid content
    resp = client.get(f"/api/projects/{project_id}/captions.ass", headers=headers)
    assert resp.status_code == 200
    assert "text/x-ssa" in resp.headers.get("content-type", "")
    assert "Test Caption" in resp.text
