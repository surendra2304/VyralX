"""Durable topic-to-video pipeline using official stock footage and local/verified TTS."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Asset, ContentPack, RenderJob, Source, VideoProject, utcnow
from app.services.captions import segment_script, write_srt
from app.services.content import generate_content_pack
from app.services.discovery import discover_youtube_videos
from app.services.trends import rank_candidates
from app.services.montage import render_montage
from app.services.pexels import import_video_file, search_videos
from app.services.probe import probe_media
from app.services.thumbnail import extract_thumbnail
from app.services.voiceover import synthesize_voiceover

log = logging.getLogger("vyralx.projects")


def _scene_query(topic: str, scene: dict | None, index: int) -> str:
    visual = str((scene or {}).get("visual") or (scene or {}).get("on_screen_text") or "")
    words = re.findall(r"[A-Za-z0-9]+", visual)
    topic_words = re.findall(r"[A-Za-z0-9]+", topic)
    combined = topic_words[:4] + words[:9]
    query = " ".join(combined).strip()
    return query[:200] or f"stock video scene {index + 1}"


def _choose_candidate(items: list[dict], used_ids: set[int]) -> tuple[dict, dict] | None:
    candidates = []
    for item in items:
        try:
            video_id = int(item["video_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if video_id in used_ids:
            continue
        files = [
            f for f in item.get("video_files", [])
            if f.get("file_type") == "video/mp4" and int(f.get("id") or 0) > 0
        ]
        if not files:
            continue
        # Prefer HD/near-1080p files; avoid giant 4K assets on the small VM.
        files.sort(
            key=lambda f: (
                1 if str(f.get("quality", "")).lower() == "hd" else 0,
                min(int(f.get("width") or 0), 1920) * min(int(f.get("height") or 0), 1920),
            ),
            reverse=True,
        )
        candidates.append((item, files[0]))
    return candidates[0] if candidates else None


def _resolve_trending_topic(project: VideoProject, db: Session) -> None:
    if not project.auto_discover_trend or project.trend_source_video_id:
        return
    query = project.trend_query.strip() or project.topic.strip()
    if not query or query.lower() == "trending topic":
        query = "technology science education"
    candidates = discover_youtube_videos(query, max(3, min(project.trend_max_results, 25)), "viewCount")
    ranked = rank_candidates(candidates)
    if not ranked:
        raise RuntimeError("YouTube discovery returned no candidate trends for the configured query")
    chosen = ranked[0]
    title = str(chosen.get("title") or "").strip()
    video_id = str(chosen.get("video_id") or "").strip()
    if not title or not video_id:
        raise RuntimeError("Top trend candidate lacked a title or video ID")
    project.topic = title[:500]
    project.trend_source_video_id = video_id[:100]
    project.trend_source_url = str(chosen.get("url") or ("https://www.youtube.com/watch?v=" + video_id))[:2048]
    project.trend_score = float(chosen.get("trend_score") or 0.0)
    project.updated_at = utcnow()
    db.commit()
    log.info("Selected YouTube metadata trend project_id=%s video_id=%s score=%s; no source media is copied", project.id, video_id, project.trend_score)


def _get_or_generate_content(project: VideoProject, db: Session) -> ContentPack:
    if project.content_pack_id:
        existing = db.get(ContentPack, project.content_pack_id)
        if existing is not None:
            return existing
    data = generate_content_pack(
        project.topic,
        video_format=project.video_format,
        audience=project.audience,
        tone=project.tone,
        target_seconds=project.target_seconds,
    )
    record = ContentPack(
        topic=project.topic,
        video_format=project.video_format,
        status="generated",
        pack_json=json.dumps(data, ensure_ascii=False),
        provider_model=str(data.get("provider_model", ""))[:200],
    )
    db.add(record)
    db.flush()
    project.content_pack_id = record.id
    project.updated_at = utcnow()
    db.commit()
    db.refresh(project)
    db.refresh(record)
    return record


def _ensure_scene_assets(project: VideoProject, pack: dict, db: Session) -> list[Asset]:
    settings = get_settings()
    if not project.confirm_pexels_license:
        raise ValueError("Operator must explicitly confirm review of the Pexels license before project creation")
    scene_plan = pack.get("scene_plan") if isinstance(pack.get("scene_plan"), list) else []
    asset_ids = [int(value) for value in json.loads(project.asset_ids_json or "[]")]
    assets: list[Asset] = []
    used_video_ids: set[int] = set()
    for asset_id in asset_ids:
        asset = db.get(Asset, asset_id)
        if asset is not None and Path(asset.file_path).is_file():
            assets.append(asset)
            source = db.get(Source, asset.source_id) if asset.source_id else None
            if source and source.platform == "pexels":
                match = re.search(r"/video/(\d+)", source.source_url)
                if match:
                    used_video_ids.add(int(match.group(1)))

    orientation = "portrait" if project.video_format == "shorts" else "landscape"
    needed = project.scene_count
    for index in range(len(assets), needed):
        scene = scene_plan[index] if index < len(scene_plan) and isinstance(scene_plan[index], dict) else {}
        query = _scene_query(project.topic, scene, index)
        results = search_videos(query, max_results=10, orientation=orientation)
        chosen = _choose_candidate(results, used_video_ids)
        if chosen is None:
            # Broaden from a scene-specific phrase to the overall topic before failing.
            results = search_videos(project.topic, max_results=15, orientation=orientation)
            chosen = _choose_candidate(results, used_video_ids)
        if chosen is None:
            raise RuntimeError(f"No downloadable Pexels MP4 candidate found for scene {index + 1}")
        video, media_file = chosen
        video_id = int(video["video_id"])
        imported = import_video_file(
            video_id,
            int(media_file["id"]),
            title=str(video.get("creator") or "Pexels stock") + " — " + query[:180],
            max_bytes=min(settings.max_upload_mb, settings.max_stock_clip_mb) * 1024 * 1024,
        )
        source_url = str(imported["source_url"])
        source = Source(
            title=imported["title"],
            source_url=source_url,
            platform="pexels",
            creator=imported["creator"],
            license_name="Pexels Content License",
            permission_reference="https://www.pexels.com/license/",
            rights_verified=True,
            status="licensed",
            notes=(
                "Imported by a project after explicit operator confirmation of Pexels licensing. "
                "Source audio is discarded by the montage renderer; credit the creator where possible."
            ),
        )
        db.add(source)
        db.flush()
        asset = Asset(
            source_id=source.id,
            title=imported["title"],
            file_path=imported["file_path"],
            rights_verified=True,
            **imported["metadata"],
        )
        db.add(asset)
        db.flush()
        assets.append(asset)
        used_video_ids.add(video_id)
        asset_ids.append(asset.id)
        project.asset_ids_json = json.dumps(asset_ids)
        project.primary_asset_id = assets[0].id
        project.updated_at = utcnow()
        db.commit()
        db.refresh(asset)
        db.refresh(project)
    if len(assets) < needed:
        raise RuntimeError("Video project could not assemble all requested stock scenes")
    for asset in assets:
        source = db.get(Source, asset.source_id) if asset.source_id else None
        if not asset.rights_verified or source is None or source.platform != "pexels":
            raise ValueError("Every project scene must retain its licensed Pexels source record")
        if not Path(asset.file_path).is_file():
            raise FileNotFoundError("A project scene file disappeared from media storage")
    return assets[:needed]


def execute_project_pipeline(project_id: int, db: Session) -> None:
    """Generate script, source licensed stock scenes, narrate, render, and record output."""
    settings = get_settings()
    project = db.get(VideoProject, project_id)
    if project is None:
        return
    subtitle_path: Path | None = None
    output_path: Path | None = None
    render_job: RenderJob | None = None
    try:
        project.status = "running"
        project.started_at = project.started_at or utcnow()
        project.updated_at = utcnow()
        project.error = ""
        db.commit()

        _resolve_trending_topic(project, db)
        content_record = _get_or_generate_content(project, db)
        pack = json.loads(content_record.pack_json)
        script = str(pack.get("script") or pack.get("voiceover") or "").strip()
        if not script:
            raise ValueError("Inference produced an empty script")
        assets = _ensure_scene_assets(project, pack, db)

        voice_path = ""
        if project.use_voiceover:
            existing_voice = Path(content_record.voiceover_path).resolve() if content_record.voiceover_path else None
            if (
                content_record.voiceover_status == "ready"
                and existing_voice is not None
                and settings.media_dir.resolve() in existing_voice.parents
                and existing_voice.is_file()
            ):
                voice_path = str(existing_voice)
            else:
                voice = synthesize_voiceover(str(pack.get("voiceover") or script))
                voice_path = str(voice["file_path"])
                content_record.voiceover_path = voice_path
                content_record.voiceover_status = "ready"
                db.commit()

        segments = segment_script(script, project.target_seconds)
        subtitle_dir = settings.data_dir / "subtitles"
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        subtitle_path = subtitle_dir / f"project-{project.id}-attempt-{project.attempts}.srt"
        write_srt(segments, subtitle_path)
        render_job = RenderJob(
            asset_id=assets[0].id,
            preset=project.video_format,
            status="running",
            attempts=1,
            started_at=utcnow(),
            options_json=json.dumps({
                "project_id": project.id,
                "montage_asset_ids": [asset.id for asset in assets],
                "subtitle_segments": segments,
                "voiceover_path": voice_path,
                "fit_mode": "pad",
                "target_seconds": project.target_seconds,
            }, ensure_ascii=False),
            project_id=project.id,
        )
        db.add(render_job)
        db.flush()
        project.status = "rendering"
        project.render_job_id = render_job.id
        project.primary_asset_id = assets[0].id
        project.asset_ids_json = json.dumps([asset.id for asset in assets])
        project.updated_at = utcnow()
        db.commit()
        db.refresh(render_job)
        db.refresh(project)

        output_path = settings.render_dir / f"{project.project_key}-attempt-{project.attempts}.mp4"
        rendered = render_montage(
            [asset.file_path for asset in assets],
            output_path,
            project.video_format,
            target_seconds=project.target_seconds,
            fit_mode="pad",
            subtitle_file=subtitle_path,
            voiceover_path=voice_path or None,
        )
        metadata = probe_media(rendered)
        if float(metadata.get("duration_seconds") or 0) <= 0:
            raise RuntimeError("Rendered project did not have a readable positive duration")
        thumbnail = settings.render_dir / f"{project.project_key}-thumbnail.jpg"
        extract_thumbnail(rendered, thumbnail, min(1.0, max(0.0, project.target_seconds / 4)))
        render_job.status = "completed"
        render_job.output_path = rendered
        render_job.error = ""
        render_job.completed_at = utcnow()
        render_job.updated_at = utcnow()
        project.thumbnail_path = str(thumbnail)
        project.status = "completed"
        project.completed_at = utcnow()
        project.updated_at = utcnow()
        project.error = ""
        db.commit()
        log.info(
            "Video project completed project_key=%s project_id=%s render_job_id=%s scenes=%s",
            project.project_key, project.id, render_job.id, len(assets),
        )
    except Exception as exc:
        db.rollback()
        project = db.get(VideoProject, project_id)
        if project is not None:
            project.status = "failed"
            project.error = f"{type(exc).__name__}: {exc}"[:3000]
            project.completed_at = utcnow()
            project.updated_at = utcnow()
            if render_job is not None:
                render_row = db.get(RenderJob, render_job.id)
                if render_row is not None and render_row.status != "completed":
                    render_row.status = "failed"
                    render_row.error = project.error
                    render_row.completed_at = utcnow()
                    render_row.updated_at = utcnow()
            db.commit()
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        log.exception("Video project failed project_id=%s", project_id)
    finally:
        if subtitle_path is not None:
            subtitle_path.unlink(missing_ok=True)
