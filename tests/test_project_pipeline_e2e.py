"""End-to-end project pipeline checks with providers and FFmpeg mocked at boundaries."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.database import SessionLocal
from app.models import Asset, ContentPack, RenderJob, Source, VideoProject
from app.services import project_pipeline


def test_project_pipeline_persists_render_captions_provenance_and_qa(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        data_dir=tmp_path / "data",
        media_dir=tmp_path / "media",
        render_dir=tmp_path / "renders",
        max_upload_mb=256,
        max_stock_clip_mb=150,
    )
    settings.data_dir.mkdir(parents=True)
    settings.render_dir.mkdir(parents=True)
    monkeypatch.setattr(project_pipeline, "get_settings", lambda: settings)

    def fake_render(asset_paths, output_path, video_format, **kwargs):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake rendered mp4")
        assert len(asset_paths) == 2
        assert kwargs["subtitle_file"].is_file()
        assert kwargs["voiceover_path"] is None
        return str(output_path)

    def fake_probe(_path):
        return {
            "duration_seconds": 30.0,
            "width": 1080,
            "height": 1920,
            "audio_stream_count": 0,
        }

    def fake_thumbnail(video_path, thumbnail_path, _timestamp):
        assert Path(video_path).is_file()
        thumbnail_path = Path(thumbnail_path)
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        thumbnail_path.write_bytes(b"fake thumbnail")

    monkeypatch.setattr(project_pipeline, "render_montage", fake_render)
    monkeypatch.setattr(project_pipeline, "probe_media", fake_probe)
    monkeypatch.setattr(
        project_pipeline,
        "analyze_media_signals",
        lambda *_args, **_kwargs: {
            "status": "analyzed",
            "black_intervals": [],
            "silence_intervals": [],
            "audio_analyzed": False,
            "thresholds": {},
        },
    )
    monkeypatch.setattr(project_pipeline, "extract_thumbnail", fake_thumbnail)
    monkeypatch.setattr(project_pipeline, "sync_project_memory", lambda _project_id, _db: {"status": "disabled"})

    suffix = uuid4().hex[:12]
    project_id = None
    asset_ids = []
    content_id = None
    render_id = None
    try:
        script = "Solar panels convert sunlight into electricity. Clean energy can reduce emissions."
        with SessionLocal() as db:
            pack = ContentPack(
                topic="Solar power",
                video_format="shorts",
                status="generated",
                pack_json=json.dumps({
                    "script": script,
                    "voiceover": script,
                    "title_options": ["How solar power works"],
                    "fact_check_notes": ["Review any numeric claims before publishing."],
                }),
            )
            db.add(pack)
            db.flush()
            content_id = pack.id

            project = VideoProject(
                project_key="e2e-" + suffix,
                topic="How solar panels work",
                video_format="shorts",
                target_seconds=30,
                scene_count=2,
                confirm_pexels_license=True,
                use_voiceover=False,
                status="queued",
                content_pack_id=pack.id,
                attempts=1,
            )
            db.add(project)
            db.flush()
            project_id = project.id

            for index in range(2):
                clip_path = tmp_path / f"clip-{index}.mp4"
                clip_path.write_bytes(b"fake licensed source clip")
                source = Source(
                    title=f"Test Pexels clip {index}",
                    source_url=f"https://www.pexels.com/video/test-stock-clip-{suffix}{index}/",
                    platform="pexels",
                    creator=f"Creator {index}",
                    license_name="Pexels Content License",
                    permission_reference="https://www.pexels.com/license/",
                    rights_verified=True,
                    status="licensed",
                )
                db.add(source)
                db.flush()
                asset = Asset(
                    source_id=source.id,
                    title=f"Test clip {index}",
                    file_path=str(clip_path),
                    duration_seconds=20,
                    width=1920,
                    height=1080,
                    rights_verified=True,
                )
                db.add(asset)
                db.flush()
                asset_ids.append(asset.id)

            project.asset_ids_json = json.dumps(asset_ids)
            db.commit()
            project_pipeline.execute_project_pipeline(project_id, db)
            db.refresh(project)
            assert project.status == "completed", project.error
            assert project.render_job_id is not None
            assert Path(project.thumbnail_path).is_file()
            assert Path(settings.render_dir / f"{project.project_key}-attempt-1.mp4").is_file()

            caption_path = settings.data_dir / "subtitles" / f"project-{project.id}-attempt-1.srt"
            assert caption_path.is_file()
            assert "Solar panels convert sunlight into electricity." in caption_path.read_text(encoding="utf-8")

            render = db.get(RenderJob, project.render_job_id)
            assert render is not None and render.status == "completed"
            render_id = render.id
            pack = db.get(ContentPack, project.content_pack_id)
            assert pack is not None
            generated = json.loads(pack.pack_json)
            quality = generated["production_qa"]
            assert quality["status"] == "ready_for_operator_review"
            assert quality["automatic_publish_approval"] is False
            assert quality["warning_count"] == 0
            assert len(generated.get("production_qa", {}).get("checks", [])) >= 7
            assert len(json.loads(project.asset_ids_json)) == 2
    finally:
        with SessionLocal() as db:
            if render_id is not None:
                db.query(RenderJob).filter(RenderJob.id == render_id).delete()
            if project_id is not None:
                db.query(VideoProject).filter(VideoProject.id == project_id).delete()
            if content_id is not None:
                db.query(ContentPack).filter(ContentPack.id == content_id).delete()
            if asset_ids:
                source_ids = [
                    source_id for (source_id,) in
                    db.query(Asset.source_id).filter(Asset.id.in_(asset_ids)).all()
                    if source_id is not None
                ]
                db.query(Asset).filter(Asset.id.in_(asset_ids)).delete(synchronize_session=False)
                if source_ids:
                    db.query(Source).filter(Source.id.in_(source_ids)).delete(synchronize_session=False)
            db.commit()
    for path in [*tmp_path.glob("clip-*.mp4"), *settings.render_dir.glob("*"), *settings.data_dir.rglob("*")]:
        if path.is_file():
            path.unlink(missing_ok=True)



def test_scene_asset_recovery_truncates_excess_valid_assets_to_requested_scene_count(tmp_path, monkeypatch):
    settings = SimpleNamespace(max_upload_mb=256, max_stock_clip_mb=150)
    monkeypatch.setattr(project_pipeline, "get_settings", lambda: settings)
    suffix = uuid4().hex[:12]
    project_id = None
    asset_ids: list[int] = []
    source_ids: list[int] = []
    try:
        with SessionLocal() as db:
            project = VideoProject(
                project_key="scene-count-" + suffix,
                topic="Solar panels",
                video_format="shorts",
                target_seconds=30,
                scene_count=2,
                confirm_pexels_license=True,
                use_voiceover=False,
                status="running",
                asset_ids_json="[]",
            )
            db.add(project)
            db.flush()
            project_id = project.id
            for index, video_id in enumerate((123456, 234567, 345678)):
                clip = tmp_path / f"scene-{index}.mp4"
                clip.write_bytes(b"licensed source fixture")
                source = Source(
                    title=f"Scene source {index}",
                    source_url=f"https://www.pexels.com/video/{video_id}/",
                    platform="pexels",
                    creator=f"Creator {index}",
                    license_name="Pexels Content License",
                    permission_reference="https://www.pexels.com/license/",
                    rights_verified=True,
                    status="licensed",
                )
                db.add(source)
                db.flush()
                source_ids.append(source.id)
                asset = Asset(
                    source_id=source.id,
                    title=f"Scene asset {index}",
                    file_path=str(clip),
                    rights_verified=True,
                )
                db.add(asset)
                db.flush()
                asset_ids.append(asset.id)
            project.asset_ids_json = json.dumps(asset_ids)
            db.commit()

            recovered = project_pipeline._ensure_scene_assets(project, {"scene_plan": []}, db)

            assert [asset.id for asset in recovered] == asset_ids[:2]
            assert json.loads(project.asset_ids_json) == asset_ids[:2]
            assert project.primary_asset_id == asset_ids[0]
    finally:
        with SessionLocal() as db:
            if project_id is not None:
                db.query(VideoProject).filter(VideoProject.id == project_id).delete()
            if asset_ids:
                db.query(Asset).filter(Asset.id.in_(asset_ids)).delete(synchronize_session=False)
            if source_ids:
                db.query(Source).filter(Source.id.in_(source_ids)).delete(synchronize_session=False)
            db.commit()


@pytest.mark.parametrize(
    "stored_ids, expected_message",
    [
        ("{}", "must be a JSON array"),
        ('["not-an-id"]', "asset ID is invalid"),
        ("[true]", "asset ID is invalid"),
        ("[1.5]", "asset ID is invalid"),
        ("[-1]", "must be positive"),
    ],
)
def test_scene_asset_recovery_rejects_malformed_persisted_ids(
    tmp_path, monkeypatch, stored_ids, expected_message
):
    settings = SimpleNamespace(max_upload_mb=256, max_stock_clip_mb=150)
    monkeypatch.setattr(project_pipeline, "get_settings", lambda: settings)
    suffix = uuid4().hex[:12]
    project_id = None
    try:
        with SessionLocal() as db:
            project = VideoProject(
                project_key="bad-scene-ids-" + suffix,
                topic="Solar panels",
                video_format="shorts",
                target_seconds=30,
                scene_count=2,
                confirm_pexels_license=True,
                use_voiceover=False,
                status="running",
                asset_ids_json=stored_ids,
            )
            db.add(project)
            db.commit()
            project_id = project.id
            with pytest.raises(ValueError, match=expected_message):
                project_pipeline._ensure_scene_assets(project, {"scene_plan": []}, db)
    finally:
        with SessionLocal() as db:
            if project_id is not None:
                db.query(VideoProject).filter(VideoProject.id == project_id).delete()
                db.commit()
