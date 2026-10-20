"""Deep unit tests for task_dispatch and voiceover synthesis modules."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.database import SessionLocal
from app.models import Asset, ContentPack, PublishJob, RenderJob, Source, VideoProject
from app.services.task_dispatch import dispatch_agent_task
from app.services.voiceover import synthesize_voiceover


def test_voiceover_validation_and_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.services.voiceover.get_settings",
        lambda: SimpleNamespace(
            tts_provider="espeak",
            espeak_bin="nonexistent-espeak",
            media_dir=tmp_path / "media",
            espeak_rate=160,
            espeak_voice="en",
        ),
    )

    # Empty text
    with pytest.raises(ValueError, match="must not be empty"):
        synthesize_voiceover("   ")

    # Exceed length limit
    with pytest.raises(ValueError, match="exceeds the 20000-character limit"):
        synthesize_voiceover("word " * 6000)

    # Negative target seconds
    with pytest.raises(ValueError, match="must be positive"):
        synthesize_voiceover("Valid script", target_seconds=-5)

    # Missing espeak binary
    with pytest.raises(RuntimeError, match="is not installed"):
        synthesize_voiceover("Valid script")


def test_voiceover_espeak_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "app.services.voiceover.get_settings",
        lambda: SimpleNamespace(
            tts_provider="espeak",
            espeak_bin="espeak",
            media_dir=media_dir,
            espeak_rate=160,
            espeak_voice="en",
        ),
    )
    monkeypatch.setattr("app.services.voiceover.shutil.which", lambda bin: "/usr/bin/espeak")

    def mock_subprocess_run(cmd, **kwargs):
        # cmd[2] is output path
        out_wav = Path(cmd[2])
        out_wav.write_bytes(b"RIFF" + b"\x00" * 100)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.services.voiceover.subprocess.run", mock_subprocess_run)

    res = synthesize_voiceover("Hello FRIDAY Universe", target_seconds=30)
    assert res["content_type"] == "audio/wav"
    assert res["bytes"] > 0
    assert Path(res["file_path"]).is_file()


def test_voiceover_external_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    # Missing config checks
    monkeypatch.setattr(
        "app.services.voiceover.get_settings",
        lambda: SimpleNamespace(
            tts_provider="external",
            inference_tts_url="",
            inference_tts_api_key="key",
            inference_api_key="key",
            inference_tts_model="model",
            media_dir=media_dir,
        ),
    )
    with pytest.raises(RuntimeError, match="requires INFERENCE_TTS_URL"):
        synthesize_voiceover("Test text")

    # Successful external call
    monkeypatch.setattr(
        "app.services.voiceover.get_settings",
        lambda: SimpleNamespace(
            tts_provider="external",
            inference_tts_url="http://inference:8000",
            inference_tts_path="/v1/audio/speech",
            inference_tts_api_key="friday-tts-key",
            inference_api_key="friday-tts-key",
            inference_tts_model="tts-1-hd",
            inference_tts_voice="alloy",
            inference_tts_timeout_seconds=30,
            media_dir=media_dir,
        ),
    )

    def mock_post(url, **kwargs):
        req = httpx.Request("POST", url)
        return httpx.Response(
            200,
            headers={"Content-Type": "audio/mpeg"},
            content=b"ID3" + b"\x00" * 500,
            request=req,
        )

    monkeypatch.setattr("app.services.voiceover.httpx.post", mock_post)

    out = synthesize_voiceover("Autonomous voice generation")
    assert out["content_type"] == "audio/mpeg"
    assert out["bytes"] > 0
    assert Path(out["file_path"]).is_file()


def test_task_dispatch_deep(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dummy_media = tmp_path / "dispatch_media.mp4"
    dummy_media.write_bytes(b"DATA" * 500)

    monkeypatch.setattr(
        "app.services.task_dispatch.get_settings",
        lambda: SimpleNamespace(
            media_dir=tmp_path,
            youtube_data_api_key="key",
            youtube_default_privacy="private",
        ),
    )

    with SessionLocal() as db:
        source = Source(
            title="Dispatch Source",
            platform="manual",
            license_name="Standard License",
            permission_reference="DISPATCH-REF-100",
            rights_verified=True,
        )
        db.add(source)
        db.flush()

        asset = Asset(
            source_id=source.id,
            title="Dispatch Asset",
            file_path=str(dummy_media),
            duration_seconds=20.0,
            width=1080,
            height=1920,
            rights_verified=True,
        )
        pack = ContentPack(
            topic="Dispatch Topic",
            video_format="shorts",
            status="generated",
            pack_json=json.dumps({"script": "Synthesize this script."}),
        )
        db.add_all([asset, pack])
        db.commit()
        asset_id = asset.id
        pack_id = pack.id
        source_id = source.id

    try:
        with SessionLocal() as db:
            # 1. content.voiceover
            monkeypatch.setattr(
                "app.services.task_dispatch.synthesize_voiceover",
                lambda text: {"file_path": str(dummy_media), "bytes": 2000},
            )
            vo_res = dispatch_agent_task("content.voiceover", {"content_pack_id": pack_id}, db)
            assert vo_res["voiceover_status"] == "ready"
            assert vo_res["bytes"] == 2000

            # 2. project.create (both fresh and replay)
            proj_payload = {
                "project_key": "dispatch-proj-1",
                "topic": "Dispatch Project Topic",
                "video_format": "shorts",
                "target_seconds": 45,
                "scene_count": 3,
                "confirm_pexels_license": True,
                "use_voiceover": False,
            }
            p1 = dispatch_agent_task("project.create", proj_payload, db)
            assert p1["status"] == "queued"
            p1_replay = dispatch_agent_task("project.create", proj_payload, db)
            assert p1_replay["project_id"] == p1["project_id"]

            # 3. render.create
            render_payload = {
                "asset_id": asset_id,
                "preset": "shorts",
                "trim_start_seconds": 0.0,
                "trim_end_seconds": 10.0,
                "subtitle_segments": [],
            }
            r_res = dispatch_agent_task("render.create", render_payload, db)
            assert r_res["status"] == "queued"
            render_id = r_res["render_job_id"]

            # Set render to completed so publish.request can use it
            r_record = db.get(RenderJob, render_id)
            r_record.status = "completed"
            r_record.output_path = str(dummy_media)
            db.commit()

            # 4. publish.request
            pub_payload = {
                "asset_id": asset_id,
                "render_job_id": render_id,
                "title": "Dispatch Published Video",
                "description": "Video description",
                "tags": ["test"],
                "confirm_rights": True,
            }
            pub_res = dispatch_agent_task("publish.request", pub_payload, db)
            assert pub_res["status"] == "pending_approval"
            pub_id = pub_res["publish_job_id"]

            # 5. Unsupported task type
            with pytest.raises(ValueError, match="Unsupported task type"):
                dispatch_agent_task("unsupported.task.type", {}, db)

    finally:
        with SessionLocal() as db:
            p = db.get(PublishJob, pub_id) if "pub_id" in locals() else None
            r = db.get(RenderJob, render_id) if "render_id" in locals() else None
            pj = db.query(VideoProject).filter(VideoProject.project_key == "dispatch-proj-1").one_or_none()
            a = db.get(Asset, asset_id)
            c = db.get(ContentPack, pack_id)
            s = db.get(Source, source_id)
            if p:
                db.delete(p)
            if r:
                db.delete(r)
            if pj:
                db.delete(pj)
            if a:
                db.delete(a)
            if c:
                db.delete(c)
            if s:
                db.delete(s)
            db.commit()
