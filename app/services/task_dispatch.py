"""Allowlisted task handlers for the FRIDAY Universe task envelope."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Asset, ContentPack, PublishJob, RenderJob, Source, VideoProject
from app.schemas import (
    ContentGenerationRequest,
    DiscoveryRequest,
    PexelsSearchRequest,
    PublishRequest,
    RenderRequest,
    VideoProjectCreateRequest,
)
from app.services.content import generate_content_pack
from app.services.discovery import discover_youtube_videos
from app.services.pexels import search_videos
from app.services.rights import append_stock_attribution, source_is_publishable, verified_render_sources
from app.services.trends import rank_candidates
from app.services.voiceover import synthesize_voiceover


def _require_rights(asset: Asset, db: Session) -> Source:
    source = db.get(Source, asset.source_id) if asset.source_id else None
    if not asset.rights_verified or not source_is_publishable(source):
        raise ValueError("Asset requires a verified source license or permission record")
    if source is None:
        raise ValueError("Source record is missing")
    return source


def dispatch_agent_task(task_type: str, raw_input: dict[str, Any], db: Session) -> dict[str, Any]:
    """Run one explicitly supported capability; arbitrary code/URLs are never executed."""
    settings = get_settings()

    if task_type == "discover.youtube":
        request = DiscoveryRequest.model_validate(raw_input)
        results = discover_youtube_videos(request.query, request.max_results, request.order)
        items = rank_candidates(results)
        return {"query": request.query, "count": len(items), "items": items}

    if task_type == "discover.pexels":
        request = PexelsSearchRequest.model_validate(raw_input)
        items = search_videos(
            request.query, max_results=request.max_results, orientation=request.orientation
        )
        return {
            "provider": "Pexels",
            "query": request.query,
            "count": len(items),
            "items": items,
            "license_url": "https://www.pexels.com/license/",
            "attribution": "Credit the photographer when possible: https://www.pexels.com/",
        }

    if task_type == "content.generate":
        request = ContentGenerationRequest.model_validate(raw_input)
        pack = generate_content_pack(
            request.topic,
            video_format=request.video_format,
            audience=request.audience,
            tone=request.tone,
            target_seconds=request.target_seconds,
        )
        record = ContentPack(
            topic=request.topic.strip(),
            video_format=request.video_format,
            status="generated",
            pack_json=json.dumps(pack, ensure_ascii=False),
            provider_model=str(pack.get("provider_model", ""))[:200],
        )
        db.add(record)
        db.flush()
        return {"content_pack_id": record.id, "status": record.status, "content_pack": pack}

    if task_type == "content.voiceover":
        content_id = int(raw_input.get("content_pack_id", 0))
        record = db.get(ContentPack, content_id)
        if record is None:
            raise ValueError("Content pack not found")
        pack = json.loads(record.pack_json)
        script = str(pack.get("voiceover") or pack.get("script") or "").strip()
        if not script:
            raise ValueError("Content pack contains no voiceover script")
        output = synthesize_voiceover(script)
        record.voiceover_path = str(output["file_path"])
        record.voiceover_status = "ready"
        db.flush()
        return {
            "content_pack_id": record.id,
            "voiceover_status": record.voiceover_status,
            "bytes": output["bytes"],
        }

    if task_type == "project.create":
        request = VideoProjectCreateRequest.model_validate(raw_input)
        if not request.confirm_pexels_license:
            raise ValueError("confirm_pexels_license must be true after reviewing the Pexels license")
        if request.auto_discover_trend and not settings.youtube_data_api_key:
            raise ValueError("Automatic trend discovery requires YOUTUBE_DATA_API_KEY")
        existing = db.query(VideoProject).filter(VideoProject.project_key == request.project_key).one_or_none()
        if existing is not None:
            same = (
                existing.auto_discover_trend == request.auto_discover_trend
                and existing.trend_query == request.trend_query.strip()
                and existing.trend_max_results == request.trend_max_results
                and existing.video_format == request.video_format
                and existing.target_seconds == request.target_seconds
                and existing.audience == request.audience
                and existing.tone == request.tone
                and existing.scene_count == request.scene_count
                and existing.confirm_pexels_license == request.confirm_pexels_license
                and existing.use_voiceover == request.use_voiceover
                and (request.auto_discover_trend or existing.topic == request.topic.strip())
            )
            if not same:
                raise ValueError("project_key already exists with different project settings")
            return {"project_id": existing.id, "project_key": existing.project_key, "status": existing.status}
        project = VideoProject(
            project_key=request.project_key,
            topic=request.topic.strip(),
            auto_discover_trend=request.auto_discover_trend,
            trend_query=request.trend_query.strip(),
            trend_max_results=request.trend_max_results,
            video_format=request.video_format,
            target_seconds=request.target_seconds,
            audience=request.audience,
            tone=request.tone,
            scene_count=request.scene_count,
            confirm_pexels_license=request.confirm_pexels_license,
            use_voiceover=request.use_voiceover,
            status="queued",
        )
        db.add(project)
        db.flush()
        return {"project_id": project.id, "project_key": project.project_key, "status": project.status}

    if task_type == "render.create":
        request = RenderRequest.model_validate(raw_input)
        asset = db.get(Asset, request.asset_id)
        if asset is None:
            raise ValueError("Asset not found")
        _require_rights(asset, db)
        if asset.duration_seconds <= 0:
            raise ValueError("Asset duration could not be verified by FFprobe")
        clip_end = request.trim_end_seconds if request.trim_end_seconds is not None else asset.duration_seconds
        if clip_end > asset.duration_seconds + 0.05:
            raise ValueError("trim_end_seconds exceeds source duration")
        clip_length = clip_end - request.trim_start_seconds
        if clip_length <= 0:
            raise ValueError("Trim range has no positive duration")
        if any(cue.end_seconds > clip_length for cue in request.subtitle_segments):
            raise ValueError("Subtitle times must fit inside the trimmed output duration")
        options = request.model_dump(
            mode="json", exclude={"asset_id", "preset", "content_pack_id"}
        )
        if request.content_pack_id is not None:
            pack = db.get(ContentPack, request.content_pack_id)
            if pack is None or pack.voiceover_status != "ready" or not pack.voiceover_path:
                raise ValueError("Generate voiceover before attaching content_pack_id to a render")
            voice_path = Path(pack.voiceover_path).resolve()
            if settings.media_dir.resolve() not in voice_path.parents or not voice_path.is_file():
                raise ValueError("Voiceover file is missing or outside VyralX media storage")
            options["voiceover_path"] = str(voice_path)
        job = RenderJob(
            asset_id=asset.id,
            preset=request.preset,
            status="queued",
            options_json=json.dumps(options, ensure_ascii=False),
        )
        db.add(job)
        db.flush()
        return {"render_job_id": job.id, "status": job.status}

    if task_type == "publish.request":
        request = PublishRequest.model_validate(raw_input)
        asset = db.get(Asset, request.asset_id)
        if asset is None:
            raise ValueError("Asset not found")
        _require_rights(asset, db)
        if not request.confirm_rights:
            raise ValueError("confirm_rights must be true before creating a publish request")
        render = db.get(RenderJob, request.render_job_id)
        if (
            render is None or render.asset_id != asset.id or render.status != "completed"
            or not Path(render.output_path).is_file()
        ):
            raise ValueError("Select a completed render belonging to this asset")
        render_sources = verified_render_sources(render, db)
        publish_description = append_stock_attribution(request.description, render_sources)
        privacy = request.privacy_status or settings.youtube_default_privacy
        if request.scheduled_at and privacy != "private":
            raise ValueError("Scheduled YouTube uploads must use private privacy with publishAt")
        scheduled_at = (
            request.scheduled_at.isoformat().replace("+00:00", "Z")
            if request.scheduled_at else ""
        )
        job = PublishJob(
            asset_id=asset.id,
            render_job_id=render.id,
            title=request.title,
            description=publish_description,
            tags_json=json.dumps(request.tags[:30]),
            privacy_status=privacy,
            scheduled_at=scheduled_at,
            status="pending_approval",
        )
        db.add(job)
        db.flush()
        return {
            "publish_job_id": job.id,
            "status": job.status,
            "message": "Explicit publish approval is still required",
        }

    raise ValueError(f"Unsupported task type: {task_type}")
