"""Durable topic-to-video pipeline using official stock footage and local/verified TTS."""
from __future__ import annotations

import json
from hashlib import sha256
import logging
import math
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
from app.services.peers import configured_peers, get_peer_json, post_peer_json
from app.services.renderer import PRESETS
from app.services.thumbnail import extract_thumbnail
from app.services.rights import is_project_scene_publishable
from app.services.project_quality import build_project_quality_report
from app.services.intelx import normalize_intelx_reports
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
    candidates = discover_youtube_videos(query, max(3, min(project.trend_max_results, 25)), "date")
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


def _fetch_intelx_research(project: VideoProject) -> tuple[list[dict], str]:
    """Fetch and normalize topic-relevant reports with an auditable outcome status."""
    try:
        if "intelx" not in configured_peers():
            return [], "not_configured"
        result = get_peer_json(
            "intelx",
            "/api/v1/research/query",
            {"sector": project.topic[:200], "limit": 5},
            timeout_seconds=8.0,
        )
        if isinstance(result, dict) and (
            result.get("error")
            or str(result.get("status") or "").casefold() in {"error", "failed", "failure"}
        ):
            log.warning("IntelX returned an error envelope project_id=%s", project.id)
            return [], "provider_error"
        if not isinstance(result, (list, dict)):
            return [], "invalid_response"
        reports = normalize_intelx_reports(result, project.topic)
        return (reports, "used") if reports else ([], "no_relevant_reports")
    except Exception as exc:
        log.warning("Optional IntelX enrichment unavailable project_id=%s error_type=%s", project.id, type(exc).__name__)
        return [], "unavailable"


_MEMORA_PRIVATE_NAMESPACE = "memora://vyralx/private"
_MEMORA_ERROR_STATES = {"error", "failed", "failure", "rejected", "blocked"}


class _MemoraProviderError(RuntimeError):
    """Memora explicitly returned an error envelope or failed status."""



def _memora_collection_items(value, *, depth: int = 0) -> list | None:
    """Unwrap known JSON collection envelopes without treating success metadata as memories."""
    if depth > 4:
        return None
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return None
    status = str(value.get("status") or "").strip().casefold()
    if value.get("error") or value.get("success") is False or status in _MEMORA_ERROR_STATES:
        raise _MemoraProviderError("Memora search returned an error envelope")
    for key in ("items", "memories", "results", "matches"):
        if isinstance(value.get(key), list):
            return value[key]
    for key in ("result", "response", "payload", "data"):
        nested = value.get(key)
        if isinstance(nested, (dict, list)):
            items = _memora_collection_items(nested, depth=depth + 1)
            if items is not None:
                return items
    return None


def _normalize_memora_memory(item: dict) -> dict | None:
    """Project one provider result into the bounded, untrusted continuity schema."""
    record = dict(item)
    for key in ("memory", "document", "record"):
        nested = record.get(key)
        if isinstance(nested, dict):
            record = {**record, **nested}
            break

    namespace = record.get("namespace_path") or record.get("target_namespace_path") or record.get("namespace")
    if namespace and str(namespace).rstrip("/") != _MEMORA_PRIVATE_NAMESPACE:
        return None

    memory_id = str(record.get("id") or record.get("memory_id") or record.get("document_id") or "").strip()
    raw_content = record.get("content_text") or record.get("content") or record.get("text") or ""
    if isinstance(raw_content, dict):
        raw_content = raw_content.get("text") or raw_content.get("content_text") or ""
    content = str(raw_content or "").strip()
    if not memory_id or not content:
        return None

    try:
        importance = float(record.get("importance", 0.0))
    except (TypeError, ValueError):
        importance = 0.0
    if not math.isfinite(importance):
        importance = 0.0
    importance = min(1.0, max(0.0, importance))
    return {
        "id": memory_id[:120],
        "memory_type": str(record.get("memory_type") or record.get("type") or "")[:40],
        "content_text": content[:1200],
        "importance": importance,
        "created_at": str(record.get("created_at") or record.get("stored_at") or "")[:80],
    }


def _memora_memory_receipt(response: dict) -> str:
    """Extract a real memory ID; never mark a failed provider envelope as stored."""
    current: object = response
    for _ in range(5):
        if not isinstance(current, dict):
            break
        status = str(current.get("status") or "").strip().casefold()
        if current.get("error") or current.get("success") is False or status in _MEMORA_ERROR_STATES:
            raise RuntimeError("Memora write returned an error envelope")
        memory_id = str(current.get("memory_id") or current.get("id") or current.get("document_id") or "").strip()
        if memory_id:
            return memory_id[:128]
        nested = next(
            (current[key] for key in ("memory", "receipt", "result", "response", "data")
             if isinstance(current.get(key), dict)),
            None,
        )
        if nested is None:
            break
        current = nested
    raise RuntimeError("Memora response did not include a successful memory receipt")


def _fetch_memora_context(project: VideoProject) -> tuple[list[dict], str]:
    """Read bounded, topic-relevant VyralX memories from its private namespace only."""
    settings = get_settings()
    if not settings.memora_read_enabled:
        return [], "disabled"
    if "memora" not in configured_peers():
        return [], "not_configured"
    try:
        result = get_peer_json(
            "memora",
            "/v1/memories/search",
            {
                "q": project.topic[:500],
                "namespace_path": _MEMORA_PRIVATE_NAMESPACE,
                "limit": 5,
                "min_score": 0.2,
            },
            timeout_seconds=8.0,
        )
        if isinstance(result, dict) and (
            result.get("error")
            or result.get("success") is False
            or str(result.get("status") or "").strip().casefold() in _MEMORA_ERROR_STATES
        ):
            log.warning("Memora search returned an error envelope project_id=%s", project.id)
            return [], "provider_error"
        result_items = _memora_collection_items(result)
        if result_items is None:
            return [], "invalid_response"
        items = []
        for raw_item in result_items[:30]:
            if not isinstance(raw_item, dict):
                continue
            item = _normalize_memora_memory(raw_item)
            if item is None:
                continue
            items.append(item)
            if len(items) == 5:
                break
        return items, "used" if items else "no_matches"
    except _MemoraProviderError as exc:
        log.warning("Memora search provider error project_id=%s error_type=%s", project.id, type(exc).__name__)
        return [], "provider_error"
    except Exception as exc:
        log.warning("Optional Memora context unavailable project_id=%s error_type=%s", project.id, type(exc).__name__)
        return [], "unavailable"


def _get_or_generate_content(project: VideoProject, db: Session) -> ContentPack:
    if project.content_pack_id:
        existing = db.get(ContentPack, project.content_pack_id)
        if existing is not None:
            return existing
    research, intelx_status = _fetch_intelx_research(project)
    memora_context, memora_context_status = _fetch_memora_context(project)
    data = generate_content_pack(
        project.topic,
        video_format=project.video_format,
        audience=project.audience,
        tone=project.tone,
        target_seconds=project.target_seconds,
        research_context=research,
        memora_context=memora_context,
    )
    data["intelx_research_context"] = research
    data["intelx_status"] = intelx_status
    data["memora_private_context"] = memora_context
    data["memora_context_status"] = memora_context_status
    data["research_status"] = "used" if research else "not_available"
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
    try:
        stored_asset_ids = json.loads(project.asset_ids_json or "[]")
    except (TypeError, ValueError):
        raise ValueError("Stored project scene asset IDs are not valid JSON") from None
    if not isinstance(stored_asset_ids, list):
        raise ValueError("Stored project scene asset IDs must be a JSON array")

    asset_ids: list[int] = []
    for value in stored_asset_ids:
        if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
            raise ValueError("Stored project scene asset ID is invalid")
        try:
            asset_id = int(value)
        except (TypeError, ValueError):
            raise ValueError("Stored project scene asset ID is invalid") from None
        if asset_id <= 0:
            raise ValueError("Stored project scene asset ID must be positive")
        if asset_id not in asset_ids:
            asset_ids.append(asset_id)

    assets: list[Asset] = []
    used_video_ids: set[int] = set()
    needed = int(project.scene_count)
    for asset_id in asset_ids:
        if len(assets) >= needed:
            break
        asset = db.get(Asset, asset_id)
        if asset is not None and Path(asset.file_path).is_file():
            assets.append(asset)
            source = db.get(Source, asset.source_id) if asset.source_id else None
            if source and source.platform == "pexels":
                match = re.search(r"/video/[^/?#]*?(\d+)(?:/|$)", source.source_url)
                if match:
                    used_video_ids.add(int(match.group(1)))

    # Keep persisted assets, rendered scene count and the primary asset aligned
    # when recovering older/corrupt jobs containing extra valid asset IDs.
    asset_ids = [asset.id for asset in assets]
    project.asset_ids_json = json.dumps(asset_ids)
    project.primary_asset_id = assets[0].id if assets else None
    orientation = "portrait" if project.video_format == "shorts" else "landscape"
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
        if not is_project_scene_publishable(asset, source):
            raise ValueError(
                "Every project scene must retain a verified Pexels source record with valid official source and license evidence"
            )
        if not Path(asset.file_path).is_file():
            raise FileNotFoundError("A project scene file disappeared from media storage")
    return assets[:needed]


def sync_project_memory(project_id: int, db: Session) -> dict:
    """Optionally store a private, idempotent completion summary in Memora."""
    project = db.get(VideoProject, project_id)
    if project is None:
        raise ValueError("Video project not found")
    if project.status != "completed":
        raise ValueError("Only completed projects can be written to Memora")
    if project.memora_memory_status == "stored" and project.memora_memory_id:
        return {"status": "stored", "memory_id": project.memora_memory_id, "idempotent_replay": True}
    settings = get_settings()
    if not settings.memora_write_enabled:
        project.memora_memory_status = "disabled"
        db.commit()
        return {"status": "disabled", "memory_id": None}
    if "memora" not in configured_peers():
        project.memora_memory_status = "not_configured"
        db.commit()
        return {"status": "not_configured", "memory_id": None}
    pack = {}
    if project.content_pack_id:
        record = db.get(ContentPack, project.content_pack_id)
        if record is not None:
            try:
                pack = json.loads(record.pack_json or "{}")
            except ValueError:
                pack = {}
    try:
        asset_ids = [int(value) for value in json.loads(project.asset_ids_json or "[]")][:4]
    except (ValueError, TypeError):
        asset_ids = []
    source_urls = []
    for asset_id in asset_ids:
        asset = db.get(Asset, asset_id)
        source = db.get(Source, asset.source_id) if asset and asset.source_id else None
        if source and source.source_url:
            source_urls.append(str(source.source_url)[:2048])
    title_options = pack.get("title_options", []) if isinstance(pack.get("title_options"), list) else []
    research_items = pack.get("intelx_research_context", [])
    if not isinstance(research_items, list):
        research_items = []
    summary = {
        "event": "video_project_completed",
        "project_key": project.project_key,
        "project_id": project.id,
        "topic": project.topic,
        "video_format": project.video_format,
        "target_seconds": project.target_seconds,
        "content_pack_id": project.content_pack_id,
        "render_job_id": project.render_job_id,
        "asset_ids": asset_ids,
        "title_options": [str(value)[:100] for value in title_options[:5]],
        "research_status": str(pack.get("research_status") or "not_available"),
        "intelx_status": str(pack.get("intelx_status") or "not_reported"),
        "research_report_ids": [
            str(item.get("report_id"))[:120]
            for item in research_items
            if isinstance(item, dict) and item.get("report_id")
        ][:5],
        "trend_source_url": project.trend_source_url or None,
        "completed_at": project.completed_at.isoformat() if project.completed_at else None,
    }
    payload = {
        "content_text": "VyralX completed a video project.\n" + json.dumps(summary, ensure_ascii=False, sort_keys=True),
        "user_id": "default_user",
        "workspace_id": "default_workspace",
        "device_id": "vyralx-worker",
        "task_id": f"vyralx-project-{project.id}",
        "idempotency_key": "vyralx-project-" + sha256(project.project_key.encode("utf-8")).hexdigest()[:32],
        "target_namespace_path": "memora://vyralx/private",
        "memory_type": "episodic",
        "source": "vyralx",
        "source_type": "project_completion",
        "trust_level": "unverified",
        "evidence_refs": list(dict.fromkeys(
            source_urls
            + ([project.trend_source_url] if project.trend_source_url else [])
            + ["https://www.pexels.com/license/"]
        ))[:20],
        "provenance": {
            "project_key": project.project_key,
            "project_id": project.id,
            "render_job_id": project.render_job_id,
            "research_status": summary["research_status"],
            "intelx_status": summary["intelx_status"],
        },
        "confidence": 0.65,
        "importance": 0.35,
    }
    project.memora_memory_status = "pending"
    db.commit()
    try:
        result = post_peer_json("memora", "/v1/memories", payload, timeout_seconds=8.0)
        memory_id = _memora_memory_receipt(result)
        project.memora_memory_id = memory_id
        project.memora_memory_status = "stored"
        db.commit()
        return {"status": "stored", "memory_id": project.memora_memory_id, "idempotent_replay": False}
    except Exception as exc:
        project.memora_memory_status = "failed"
        db.commit()
        log.warning("Memora project memory write failed project_id=%s error_type=%s", project.id, type(exc).__name__)
        return {"status": "failed", "memory_id": None, "error_type": type(exc).__name__}


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
                voice = synthesize_voiceover(str(pack.get("voiceover") or script), target_seconds=project.target_seconds)
                voice_path = str(voice["file_path"])
                content_record.voiceover_path = voice_path
                content_record.voiceover_status = "ready"
                db.commit()

        voiceover_duration: float | None = None
        if project.use_voiceover:
            voiceover_metadata = probe_media(voice_path)
            voiceover_duration = float(voiceover_metadata.get("duration_seconds") or 0)
            if (
                not math.isfinite(voiceover_duration)
                or voiceover_duration <= 0
                or int(voiceover_metadata.get("audio_stream_count") or 0) < 1
            ):
                raise RuntimeError("Narration file is not readable audio with a positive duration")

        caption_text = str(pack.get("voiceover") or script) if project.use_voiceover else script
        segments = segment_script(caption_text, project.target_seconds)
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
        actual_duration = float(metadata.get("duration_seconds") or 0)
        expected_width, expected_height = PRESETS[project.video_format]
        if not math.isfinite(actual_duration) or actual_duration <= 0:
            raise RuntimeError("Rendered project did not have a finite positive duration")
        if abs(actual_duration - project.target_seconds) > 1.5:
            raise RuntimeError(f"Rendered duration {actual_duration:.2f}s differs from target {project.target_seconds}s")
        if int(metadata.get("width") or 0) != expected_width or int(metadata.get("height") or 0) != expected_height:
            raise RuntimeError("Rendered dimensions do not match the selected video format")
        if project.use_voiceover and int(metadata.get("audio_stream_count") or 0) < 1:
            raise RuntimeError("Voiceover was requested but the rendered video has no audio stream")
        thumbnail = settings.render_dir / f"{project.project_key}-thumbnail.jpg"
        extract_thumbnail(rendered, thumbnail, min(1.0, max(0.0, project.target_seconds / 4)))
        if not thumbnail.is_file() or thumbnail.stat().st_size <= 0:
            raise RuntimeError("Thumbnail generation did not produce a usable image")
        scene_rights_checks = []
        for asset in assets:
            source = db.get(Source, asset.source_id) if asset.source_id else None
            scene_rights_checks.append(
                bool(Path(asset.file_path).is_file() and is_project_scene_publishable(asset, source))
            )
        pack["production_qa"] = build_project_quality_report(
            target_seconds=project.target_seconds,
            actual_duration=actual_duration,
            expected_width=expected_width,
            expected_height=expected_height,
            actual_width=int(metadata.get("width") or 0),
            actual_height=int(metadata.get("height") or 0),
            audio_stream_count=int(metadata.get("audio_stream_count") or 0),
            voiceover_requested=project.use_voiceover,
            voiceover_path=voice_path or None,
            voiceover_duration=voiceover_duration,
            subtitle_path=subtitle_path,
            subtitle_segments=segments,
            caption_text=caption_text,
            thumbnail_path=thumbnail,
            scene_rights_checks=scene_rights_checks,
        )
        content_record.pack_json = json.dumps(pack, ensure_ascii=False)
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
        sync_project_memory(project.id, db)
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
        # Keep successful caption files as durable review/download artifacts.
        # Failed attempts are cleaned up; the next attempt gets its own filename.
        if subtitle_path is not None and (project is None or project.status != "completed"):
            subtitle_path.unlink(missing_ok=True)
