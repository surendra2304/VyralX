import json
import logging
import shutil
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.database import Base, engine, get_db
from app.migrations import run_additive_migrations
from app.models import AgentTask, Asset, ContentPack, PublishJob, RenderJob, Source, VideoMetric, utcnow
from app.schemas import AgentTaskCancelRequest, AgentTaskRequest, ContentGenerationRequest, ContentVoiceoverRequest, DiscoveryRequest, PexelsImportRequest, PexelsSearchRequest, PublishRequest, PublishResolutionRequest, RenderRequest, SourceCreate, ThumbnailRequest
from app.security import require_api_key
from app.services.probe import probe_media
from app.services.discovery import discover_youtube_videos
from app.services.trends import rank_candidates
from app.services.content import generate_content_pack
from app.services.voiceover import synthesize_voiceover
from app.services.thumbnail import extract_thumbnail
from app.services.youtube_analytics import fetch_video_metrics
from app.services.peers import configured_peers, peer_health
from app.services.pexels import import_video_file, search_videos
from app.services.rights import source_is_publishable

settings = get_settings()
settings.prepare_directories()
Base.metadata.create_all(bind=engine)
run_additive_migrations(engine)
logging.basicConfig(level=settings.log_level)
log = logging.getLogger("vyralx")

app = FastAPI(title="VyralX", version="0.2.0",
              description="Video discovery, editing, and YouTube publishing agent")


@app.get("/health")
def health():
    return {"status": "ok", "service": "vyralx", "version": app.version}


@app.get("/ready")
def ready():
    database_ok = False
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
        database_ok = True
    except Exception:
        log.exception("Readiness database check failed")
    ffmpeg_ok = shutil.which(settings.ffmpeg_bin) is not None
    worker_ok = not settings.worker_required
    worker_status = "not_required"
    if settings.worker_required:
        heartbeat_path = settings.data_dir / "worker-heartbeat.json"
        try:
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            updated = datetime.fromisoformat(heartbeat["updated_at"])
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age = max(0.0, (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds())
            worker_ok = age <= settings.worker_heartbeat_timeout_seconds and heartbeat.get("state") != "stopped"
            worker_status = "healthy" if worker_ok else "stale"
        except (OSError, ValueError, KeyError, TypeError):
            worker_status = "missing"
    ready_state = database_ok and ffmpeg_ok and worker_ok
    response = {
        "status": "ready" if ready_state else "degraded",
        "database": "connected" if database_ok else "unavailable",
        "ffmpeg": ffmpeg_ok,
        "worker": worker_status,
    }
    return JSONResponse(content=response, status_code=200 if ready_state else 503)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VyralX Control Room</title><style>
:root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;background:#090d16;color:#edf2ff}
body{max-width:1100px;margin:0 auto;padding:28px}header{display:flex;justify-content:space-between;align-items:center;gap:20px}
h1{font-size:2.3rem;margin:0}p{color:#aab6cf}.pill{border:1px solid #2e405e;border-radius:30px;padding:8px 12px;color:#9ee7c0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:24px 0}
.card{background:#111a2a;border:1px solid #26334a;border-radius:16px;padding:18px}.card h2{font-size:1rem;margin-top:0}
button{background:#8be0b1;color:#08140f;border:0;border-radius:9px;padding:10px 14px;font-weight:700;cursor:pointer}
small{color:#aab6cf}pre{white-space:pre-wrap;word-break:break-word;color:#aee9c8}
</style></head><body><header><div><h1>VyralX <span style="color:#8be0b1">/</span></h1><p>Discover. Edit. Publish. Scale.</p></div><span class="pill" id="health">Checking API…</span></header>
<div class="grid"><section class="card"><h2>1 · Discover</h2><p>Track source links, creators, licenses and permission evidence.</p><small>Platform discovery does not imply download rights.</small></section>
<section class="card"><h2>2 · Edit</h2><p>Import authorized media and render Shorts, landscape or square outputs with FFmpeg.</p><small>Render concurrency is intentionally bounded.</small></section>
<section class="card"><h2>3 · Publish</h2><p>Queue YouTube uploads, descriptions, tags, privacy and scheduling.</p><small>Publishing stays disabled until explicitly enabled.</small></section>
<section class="card"><h2>4 · Measure</h2><p>Persist jobs and video IDs for later analytics integration.</p><small>Health does not prove external providers are configured.</small></section></div>
<section class="card"><h2>Operator quick check</h2><p>Service status</p><pre id="details">Loading…</pre><button onclick="refresh()">Refresh status</button></section>
<script>async function refresh(){try{const r=await fetch('/ready');const d=await r.json();document.getElementById('health').textContent=d.status;document.getElementById('details').textContent=JSON.stringify(d,null,2)}catch(e){document.getElementById('health').textContent='API unavailable';document.getElementById('details').textContent=String(e)}}refresh()</script>
</body></html>""")


@app.post("/api/discover", dependencies=[Depends(require_api_key)])
def discover(payload: DiscoveryRequest):
    query = payload.query.strip()
    if not query:
        raise HTTPException(422, "query must not be blank")
    try:
        items = discover_youtube_videos(query, payload.max_results, payload.order)
    except Exception as exc:
        log.error("YouTube discovery failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(502, "YouTube discovery failed; check server logs and provider configuration") from None
    # Results are leads only: no media is downloaded and rights remain unverified.
    ranked = rank_candidates(items)
    return {"query": query, "count": len(ranked), "items": ranked, "score_note": "heuristic ranking; discovery is not permission"}


@app.post("/api/sources", dependencies=[Depends(require_api_key)])
def create_source(payload: SourceCreate, db: Session = Depends(get_db)):
    source = Source(**payload.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return {"id": source.id, "status": source.status, "rights_verified": source.rights_verified}


@app.get("/api/sources", dependencies=[Depends(require_api_key)])
def list_sources(db: Session = Depends(get_db)):
    rows = db.scalars(select(Source).order_by(Source.id.desc()).limit(200)).all()
    return [{"id": s.id, "title": s.title, "source_url": s.source_url, "platform": s.platform,
             "creator": s.creator, "license_name": s.license_name,
             "permission_reference": s.permission_reference, "rights_verified": s.rights_verified,
             "status": s.status, "notes": s.notes}
            for s in rows]


@app.post("/api/assets/upload", dependencies=[Depends(require_api_key)])
async def upload_asset(file: UploadFile = File(...), title: str = "Untitled asset",
                       source_id: int | None = None, db: Session = Depends(get_db)):
    allowed = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(415, "Unsupported media extension")
    source = db.get(Source, source_id) if source_id else None
    if source_id and source is None:
        raise HTTPException(404, "Source not found")
    if source and not source_is_publishable(source):
        raise HTTPException(403, "Source rights are not verified with a license or permission reference")
    destination = (settings.media_dir / (uuid4().hex + suffix)).resolve()
    if settings.media_dir.resolve() not in destination.parents:
        raise HTTPException(400, "Invalid media path")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        with destination.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, "Upload exceeds MAX_UPLOAD_MB")
                target.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    try:
        meta = await run_in_threadpool(probe_media, destination)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(422, "Media probe failed: " + str(exc)[:300]) from exc
    asset = Asset(source_id=source_id, title=title[:300], file_path=str(destination),
                  rights_verified=bool(source and source_is_publishable(source)), **meta)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return {"id": asset.id, "title": asset.title, **meta, "rights_verified": asset.rights_verified}


@app.get("/api/assets", dependencies=[Depends(require_api_key)])
def list_assets(db: Session = Depends(get_db)):
    rows = db.scalars(select(Asset).order_by(Asset.id.desc()).limit(200)).all()
    return [{"id": a.id, "title": a.title, "duration_seconds": a.duration_seconds,
             "width": a.width, "height": a.height, "rights_verified": a.rights_verified}
            for a in rows]


@app.post("/api/render", status_code=202, dependencies=[Depends(require_api_key)])
def create_render(payload: RenderRequest, db: Session = Depends(get_db)):
    asset = db.get(Asset, payload.asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    source = db.get(Source, asset.source_id) if asset.source_id else None
    if not asset.rights_verified or not source_is_publishable(source):
        raise HTTPException(403, "Asset requires a verified license or permission record")
    if asset.duration_seconds <= 0:
        raise HTTPException(422, "Asset duration could not be verified by FFprobe")
    clip_end = payload.trim_end_seconds if payload.trim_end_seconds is not None else asset.duration_seconds
    if clip_end > asset.duration_seconds + 0.05:
        raise HTTPException(422, "trim_end_seconds exceeds the source media duration")
    clip_length = clip_end - payload.trim_start_seconds
    if clip_length <= 0:
        raise HTTPException(422, "Trim range has no positive duration")
    for segment in payload.subtitle_segments:
        if segment.end_seconds > clip_length:
            raise HTTPException(422, "Subtitle times must fit inside the trimmed clip")
    options = payload.model_dump(mode="json", exclude={"asset_id", "preset", "content_pack_id"})
    if payload.content_pack_id is not None:
        pack = db.get(ContentPack, payload.content_pack_id)
        if pack is None:
            raise HTTPException(404, "Content pack not found")
        if pack.voiceover_status != "ready" or not pack.voiceover_path:
            raise HTTPException(409, "Generate the content pack voiceover before attaching it to a render")
        voice_path = Path(pack.voiceover_path).resolve()
        if settings.media_dir.resolve() not in voice_path.parents or not voice_path.is_file():
            raise HTTPException(409, "Generated voiceover is missing or outside media storage")
        options["voiceover_path"] = str(voice_path)
    job = RenderJob(
        asset_id=asset.id,
        preset=payload.preset,
        status="queued",
        options_json=json.dumps(options, ensure_ascii=False),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return {
        "job_id": job.id,
        "status": job.status,
        "message": "Queued for the VyralX worker; poll GET /api/render for status",
    }


@app.get("/api/render", dependencies=[Depends(require_api_key)])
def list_renders(db: Session = Depends(get_db)):
    rows = db.scalars(select(RenderJob).order_by(RenderJob.id.desc()).limit(100)).all()
    return [{"id": j.id, "asset_id": j.asset_id, "preset": j.preset, "status": j.status,
             "output_path": j.output_path, "attempts": j.attempts, "error": j.error,
             "created_at": j.created_at, "started_at": j.started_at,
             "completed_at": j.completed_at} for j in rows]


@app.post("/api/publish", dependencies=[Depends(require_api_key)])
def queue_publish(payload: PublishRequest, db: Session = Depends(get_db)):
    asset = db.get(Asset, payload.asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    if not payload.confirm_rights or not asset.rights_verified:
        raise HTTPException(403, "Explicit rights confirmation and a verified source record are required")
    render = db.get(RenderJob, payload.render_job_id)
    if (
        render is None
        or render.asset_id != asset.id
        or render.status != "completed"
        or not Path(render.output_path).is_file()
    ):
        raise HTTPException(409, "Select a completed render belonging to this asset")
    privacy_status = payload.privacy_status or settings.youtube_default_privacy
    if payload.scheduled_at and privacy_status != "private":
        raise HTTPException(422, "Scheduled YouTube videos must use private privacy with publishAt")
    scheduled_at = payload.scheduled_at.isoformat().replace("+00:00", "Z") if payload.scheduled_at else ""
    source = db.get(Source, asset.source_id) if asset.source_id else None
    if not source_is_publishable(source):
        raise HTTPException(403, "Current source record does not contain verified rights evidence")
    job = PublishJob(asset_id=asset.id, render_job_id=render.id, title=payload.title,
                     description=payload.description, tags_json=json.dumps(payload.tags[:30]),
                     privacy_status=privacy_status, scheduled_at=scheduled_at, status="pending_approval")
    db.add(job)
    db.commit()
    db.refresh(job)
    return {"job_id": job.id, "status": job.status,
            "note": "Pending operator approval; call the execute endpoint only after reviewing the render and metadata"}


@app.post("/api/publish/{job_id}/execute", status_code=202, dependencies=[Depends(require_api_key)])
def execute_publish(job_id: int, db: Session = Depends(get_db)):
    """Approve a queued upload; the separate worker performs the network operation."""
    job = db.get(PublishJob, job_id)
    if job is None:
        raise HTTPException(404, "Publish job not found")
    if job.status == "queued":
        return {"job_id": job.id, "status": job.status, "message": "Already queued for the worker"}
    if job.status != "pending_approval":
        raise HTTPException(409, f"Job cannot be approved from status {job.status}")
    if not settings.youtube_upload_enabled:
        raise HTTPException(503, "YouTube publishing is disabled; enable it only after OAuth verification")
    asset = db.get(Asset, job.asset_id)
    render = db.get(RenderJob, job.render_job_id)
    source = db.get(Source, asset.source_id) if asset and asset.source_id else None
    if (
        asset is None or render is None or render.asset_id != asset.id
        or render.status != "completed" or not Path(render.output_path).is_file()
    ):
        raise HTTPException(409, "The selected completed render is missing")
    if not asset.rights_verified or not source_is_publishable(source):
        raise HTTPException(403, "Current source record does not contain verified rights evidence")
    result = db.execute(
        update(PublishJob)
        .where(PublishJob.id == job.id, PublishJob.status == "pending_approval")
        .values(status="queued", approved_at=utcnow(), updated_at=utcnow())
    )
    db.commit()
    if result.rowcount != 1:
        raise HTTPException(409, "Publish job status changed; refresh before approving")
    return {
        "job_id": job.id,
        "status": "queued",
        "message": "Approved; the VyralX worker will upload it if YouTube publishing is enabled",
    }


@app.get("/api/publish", dependencies=[Depends(require_api_key)])
def list_publish_jobs(db: Session = Depends(get_db)):
    rows = db.scalars(select(PublishJob).order_by(PublishJob.id.desc()).limit(100)).all()
    return [{"id": j.id, "asset_id": j.asset_id, "render_job_id": j.render_job_id,
             "title": j.title, "privacy_status": j.privacy_status, "scheduled_at": j.scheduled_at,
             "status": j.status, "attempts": j.attempts, "youtube_video_id": j.youtube_video_id,
             "error": j.error, "created_at": j.created_at, "approved_at": j.approved_at,
             "completed_at": j.completed_at} for j in rows]


@app.post("/api/content/generate", dependencies=[Depends(require_api_key)])
def create_content_pack(payload: ContentGenerationRequest, db: Session = Depends(get_db)):
    """Generate original, editable scripts and a scene plan using the Inference gateway."""
    try:
        pack = generate_content_pack(
            payload.topic,
            video_format=payload.video_format,
            audience=payload.audience,
            tone=payload.tone,
            target_seconds=payload.target_seconds,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception as exc:
        log.error("Content generation failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(502, "Content generation failed; check Inference configuration and logs") from None
    record = ContentPack(
        topic=payload.topic.strip(),
        video_format=payload.video_format,
        status="generated",
        pack_json=json.dumps(pack, ensure_ascii=False),
        provider_model=str(pack.get("provider_model", ""))[:200],
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "status": record.status, "content_pack": pack}


@app.get("/api/content", dependencies=[Depends(require_api_key)])
def list_content_packs(db: Session = Depends(get_db)):
    rows = db.scalars(select(ContentPack).order_by(ContentPack.id.desc()).limit(100)).all()
    return [
        {"id": row.id, "topic": row.topic, "format": row.video_format,
         "status": row.status, "provider_model": row.provider_model,
         "voiceover_status": row.voiceover_status,
         "content_pack": json.loads(row.pack_json), "created_at": row.created_at}
        for row in rows
    ]


@app.get("/api/agent/manifest", dependencies=[Depends(require_api_key)])
def agent_manifest():
    """Machine-readable VyralX capability and peer contract for FRIDAY."""
    peers = configured_peers()
    return {
        "name": "VyralX",
        "service_id": "vyralx",
        "version": app.version,
        "role": "video_discovery_production_and_youtube_distribution",
        "health_url": "/health",
        "readiness_url": "/ready",
        "authentication": {"schemes": ["Bearer", "X-API-Key"]},
        "capabilities": [
            {"id": "task.submit", "method": "POST", "path": "/api/v1/tasks"},
            {"id": "task.status", "method": "GET", "path": "/api/v1/tasks/{task_id}"},
            {"id": "discover.youtube", "method": "POST", "path": "/api/discover"},
            {"id": "discover.pexels", "method": "POST", "path": "/api/discover/pexels"},
            {"id": "asset.import.pexels", "method": "POST", "path": "/api/assets/import/pexels"},
            {"id": "content.generate", "method": "POST", "path": "/api/content/generate"},
            {"id": "content.voiceover", "method": "POST", "path": "/api/content/{content_id}/voiceover"},
            {"id": "thumbnail.create", "method": "POST", "path": "/api/thumbnails"},
            {"id": "youtube.analytics.refresh", "method": "POST", "path": "/api/analytics/refresh"},
            {"id": "source.register", "method": "POST", "path": "/api/sources"},
            {"id": "asset.import", "method": "POST", "path": "/api/assets/upload"},
            {"id": "video.render", "method": "POST", "path": "/api/render", "asynchronous": True},
            {"id": "video.publish.request", "method": "POST", "path": "/api/publish"},
            {"id": "video.publish.approve", "method": "POST", "path": "/api/publish/{job_id}/execute"},
            {"id": "video.job.retry", "method": "POST", "path": "/api/jobs/{kind}/{job_id}/retry"},
            {"id": "video.publish.resolve_uncertain", "method": "POST", "path": "/api/jobs/publish/{job_id}/resolve"},
        ],
        "peer_contract": "HTTP JSON authenticated using X-API-Key; paths must be confirmed for each peer",
        "configured_peers": sorted(peers.keys()),
        "publishing_enabled": settings.youtube_upload_enabled,
        "privacy_default": settings.youtube_default_privacy,
        "rights_gate_required": True,
        "sentinel_policy_required_for_publish": settings.sentinel_required_for_publish,
    }


@app.get("/api/agents/health", dependencies=[Depends(require_api_key)])
def agent_health():
    return {
        name: peer_health(name)
        for name in ("friday", "inference", "intelx", "memora", "sentinel")
    }


@app.post("/api/jobs/render/{job_id}/retry", status_code=202, dependencies=[Depends(require_api_key)])
def retry_render_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(RenderJob, job_id)
    if job is None:
        raise HTTPException(404, "Render job not found")
    if job.status != "failed":
        raise HTTPException(409, "Only failed render jobs can be retried")
    if job.attempts >= settings.worker_max_attempts:
        raise HTTPException(409, "Retry limit reached; inspect the stored error before resetting attempts")
    db.execute(
        update(RenderJob).where(RenderJob.id == job.id, RenderJob.status == "failed")
        .values(status="queued", error="", output_path="", updated_at=utcnow(), completed_at=None)
    )
    db.commit()
    return {"job_id": job.id, "status": "queued"}


@app.post("/api/jobs/publish/{job_id}/retry", status_code=202, dependencies=[Depends(require_api_key)])
def retry_publish_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(PublishJob, job_id)
    if job is None:
        raise HTTPException(404, "Publish job not found")
    if job.status != "failed":
        raise HTTPException(409, "Only failed publish jobs can be retried")
    if job.attempts >= settings.worker_max_attempts:
        raise HTTPException(409, "Retry limit reached; inspect the stored error before resetting attempts")
    db.execute(
        update(PublishJob).where(PublishJob.id == job.id, PublishJob.status == "failed")
        .values(status="pending_approval", error="", updated_at=utcnow(),
                completed_at=None, approved_at=None)
    )
    db.commit()
    return {"job_id": job.id, "status": "pending_approval",
            "message": "Review the job and approve it again before an external upload"}


@app.post("/api/discover/pexels", dependencies=[Depends(require_api_key)])
def discover_pexels(payload: PexelsSearchRequest):
    """Search official Pexels stock footage; candidates remain unverified until import confirmation."""
    try:
        items = search_videos(
            payload.query,
            max_results=payload.max_results,
            orientation=payload.orientation,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception as exc:
        log.error("Pexels discovery failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(502, "Pexels discovery failed; check PEXELS_API_KEY and provider status") from None
    return {
        "provider": "Pexels",
        "query": payload.query,
        "count": len(items),
        "items": items,
        "attribution": "Credit the photographer where possible: https://www.pexels.com/",
        "license_url": "https://www.pexels.com/license/",
    }


@app.post("/api/assets/import/pexels", status_code=201, dependencies=[Depends(require_api_key)])
def import_pexels_asset(payload: PexelsImportRequest, db: Session = Depends(get_db)):
    """Import from Pexels after the operator explicitly confirms license review."""
    if not payload.confirm_license:
        raise HTTPException(
            403,
            "Review https://www.pexels.com/license/ and set confirm_license=true to import this stock clip",
        )
    destination = None
    try:
        imported = import_video_file(
            payload.video_id,
            payload.video_file_id,
            title=payload.title or f"Pexels video {payload.video_id}",
            max_bytes=settings.max_upload_mb * 1024 * 1024,
        )
        destination = Path(imported["file_path"])
        source_url = imported["source_url"]
        source = Source(
            title=imported["title"],
            source_url=source_url,
            platform="pexels",
            creator=imported["creator"],
            license_name="Pexels Content License",
            permission_reference=source_url,
            rights_verified=True,
            status="licensed",
            notes=(
                "Imported via official Pexels API after explicit operator confirmation of the "
                "Pexels license. Credit the creator when possible. Review provider terms for "
                "limitations before publishing."
            ),
        )
        db.add(source)
        db.flush()
        asset = Asset(
            source_id=source.id,
            title=imported["title"],
            file_path=str(destination),
            rights_verified=True,
            **imported["metadata"],
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return {
            "asset_id": asset.id,
            "source_id": source.id,
            "title": asset.title,
            "metadata": imported["metadata"],
            "rights_verified": True,
            "creator": imported["creator"],
            "creator_url": imported["creator_url"],
            "source_url": source_url,
            "license_url": "https://www.pexels.com/license/",
            "attribution_notice": "Credit the photographer where possible.",
        }
    except ValueError as exc:
        db.rollback()
        if destination:
            destination.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from None
    except Exception as exc:
        db.rollback()
        if destination:
            destination.unlink(missing_ok=True)
        log.error("Pexels import failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(502, "Pexels import failed; check provider configuration and logs") from None

@app.post("/api/content/{content_id}/voiceover", status_code=202, dependencies=[Depends(require_api_key)])
def generate_content_voiceover(content_id: int, db: Session = Depends(get_db)):
    """Synthesize the original script through the configured Inference TTS gateway."""
    record = db.get(ContentPack, content_id)
    if record is None:
        raise HTTPException(404, "Content pack not found")
    pack = json.loads(record.pack_json)
    voiceover_text = str(pack.get("voiceover") or pack.get("script") or "").strip()
    if not voiceover_text:
        raise HTTPException(422, "Content pack contains no voiceover script")
    try:
        result = synthesize_voiceover(voiceover_text)
        record.voiceover_path = str(result["file_path"])
        record.voiceover_status = "ready"
        db.commit()
        return {
            "content_pack_id": record.id,
            "voiceover_status": record.voiceover_status,
            "bytes": result["bytes"],
            "message": "Voiceover ready; pass content_pack_id to POST /api/render",
        }
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    except Exception as exc:
        db.rollback()
        record = db.get(ContentPack, content_id)
        if record is not None:
            record.voiceover_status = "failed"
            db.commit()
        log.error("Voiceover synthesis failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(502, "Voiceover synthesis failed; check Inference TTS configuration and logs") from None


@app.post("/api/thumbnails", status_code=201, dependencies=[Depends(require_api_key)])
def create_thumbnail(payload: ThumbnailRequest, db: Session = Depends(get_db)):
    job = db.get(RenderJob, payload.render_job_id)
    if job is None:
        raise HTTPException(404, "Render job not found")
    if job.status != "completed" or not job.output_path or not Path(job.output_path).is_file():
        raise HTTPException(409, "Thumbnail extraction requires a completed render")
    try:
        metadata = probe_media(job.output_path)
        duration = float(metadata.get("duration_seconds") or 0)
        if duration <= 0 or payload.timestamp_seconds >= duration:
            raise HTTPException(422, "timestamp_seconds must be earlier than the rendered video duration")
        thumbnail_path = settings.render_dir / ("thumbnail-job-" + str(job.id) + ".jpg")
        extract_thumbnail(job.output_path, thumbnail_path, payload.timestamp_seconds)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Thumbnail extraction failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(502, "Thumbnail extraction failed; check FFmpeg and logs") from None
    return {
        "render_job_id": job.id,
        "path": "/api/thumbnails/" + str(job.id),
        "download_name": "vyralx-thumbnail-" + str(job.id) + ".jpg",
    }


@app.get("/api/thumbnails/{job_id}", dependencies=[Depends(require_api_key)])
def get_thumbnail(job_id: int):
    path = settings.render_dir / ("thumbnail-job-" + str(job_id) + ".jpg")
    if not path.is_file():
        raise HTTPException(404, "Thumbnail not found; create it with POST /api/thumbnails")
    return FileResponse(path, media_type="image/jpeg", filename="vyralx-thumbnail-" + str(job_id) + ".jpg")


@app.post("/api/analytics/refresh", dependencies=[Depends(require_api_key)])
def refresh_analytics(db: Session = Depends(get_db)):
    """Pull view/like/comment snapshots for VyralX-published videos via YouTube Data API."""
    if not settings.youtube_analytics_enabled:
        raise HTTPException(503, "Analytics is disabled; set YOUTUBE_ANALYTICS_ENABLED=true after configuration")
    jobs = db.scalars(
        select(PublishJob).where(PublishJob.status == "uploaded", PublishJob.youtube_video_id != "")
        .order_by(PublishJob.id.desc()).limit(200)
    ).all()
    by_video = {job.youtube_video_id: job for job in jobs}
    try:
        metrics = fetch_video_metrics(list(by_video))
    except Exception as exc:
        log.error("YouTube analytics refresh failed (error_type=%s)", type(exc).__name__)
        raise HTTPException(502, "Analytics refresh failed; check YouTube Data API configuration and logs") from None
    snapshots = []
    for metric in metrics:
        job = by_video.get(metric["youtube_video_id"])
        if job is None:
            continue
        record = VideoMetric(
            publish_job_id=job.id,
            youtube_video_id=metric["youtube_video_id"],
            view_count=metric["view_count"],
            like_count=metric["like_count"],
            comment_count=metric["comment_count"],
        )
        db.add(record)
        snapshots.append({
            **metric,
            "publish_job_id": job.id,
            "engagements": metric["like_count"] + metric["comment_count"],
            "engagement_per_view": round(
                (metric["like_count"] + metric["comment_count"]) / max(1, metric["view_count"]), 6
            ),
        })
    db.commit()
    return {"snapshots_saved": len(snapshots), "items": snapshots}


@app.get("/api/analytics", dependencies=[Depends(require_api_key)])
def list_analytics(db: Session = Depends(get_db)):
    rows = db.scalars(select(VideoMetric).order_by(VideoMetric.id.desc()).limit(500)).all()
    return [
        {
            "publish_job_id": row.publish_job_id,
            "youtube_video_id": row.youtube_video_id,
            "view_count": row.view_count,
            "like_count": row.like_count,
            "comment_count": row.comment_count,
            "engagements": row.like_count + row.comment_count,
            "engagement_per_view": round(
                (row.like_count + row.comment_count) / max(1, row.view_count), 6
            ),
            "fetched_at": row.fetched_at,
        }
        for row in rows
    ]

 
@app.post("/api/jobs/publish/{job_id}/resolve", dependencies=[Depends(require_api_key)])
def resolve_uncertain_publish(
    job_id: int,
    payload: PublishResolutionRequest,
    db: Session = Depends(get_db),
):
    """Reconcile a worker crash that occurred during a remote upload."""
    job = db.get(PublishJob, job_id)
    if job is None:
        raise HTTPException(404, "Publish job not found")
    if job.status != "uncertain":
        raise HTTPException(409, "Only uncertain uploads can be resolved")
    if payload.decision == "uploaded":
        job.status = "uploaded"
        job.youtube_video_id = payload.youtube_video_id.strip()
        job.error = ""
        job.completed_at = utcnow()
        job.updated_at = utcnow()
        db.commit()
        return {
            "job_id": job.id,
            "status": job.status,
            "youtube_video_id": job.youtube_video_id,
            "message": "Upload reconciled; metrics can be refreshed later",
        }
    # The operator has confirmed the remote upload did not create a video.
    # Require another explicit approval before the worker performs a new upload.
    job.status = "pending_approval"
    job.error = ""
    job.youtube_video_id = ""
    job.approved_at = None
    job.completed_at = None
    job.updated_at = utcnow()
    db.commit()
    return {
        "job_id": job.id,
        "status": job.status,
        "message": "Reconciled as not uploaded; review and approve again to retry",
    }


def _agent_task_summary(task: AgentTask) -> dict:
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "correlation_id": task.correlation_id,
        "status": task.status,
        "attempts": task.attempts,
        "error": task.error,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "updated_at": task.updated_at,
        "completed_at": task.completed_at,
    }


@app.post("/api/v1/tasks", status_code=202, dependencies=[Depends(require_api_key)])
def submit_agent_task(payload: AgentTaskRequest, db: Session = Depends(get_db)):
    """FRIDAY-compatible durable task envelope with idempotent caller-supplied task_id."""
    normalized_input = json.dumps(payload.input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    existing = db.scalar(select(AgentTask).where(AgentTask.task_id == payload.task_id))
    if existing is not None:
        if existing.task_type != payload.task_type or existing.input_json != normalized_input:
            raise HTTPException(409, "task_id already exists with a different task type or input")
        return {
            **_agent_task_summary(existing),
            "status_url": "/api/v1/tasks/" + existing.task_id,
            "idempotent_replay": True,
        }

    try:
        # Reject malformed task inputs before putting them in the persistent queue.
        if payload.task_type == "discover.youtube":
            DiscoveryRequest.model_validate(payload.input)
        elif payload.task_type == "discover.pexels":
            PexelsSearchRequest.model_validate(payload.input)
        elif payload.task_type == "content.generate":
            ContentGenerationRequest.model_validate(payload.input)
        elif payload.task_type == "content.voiceover":
            ContentVoiceoverRequest.model_validate(payload.input)
        elif payload.task_type == "render.create":
            RenderRequest.model_validate(payload.input)
        elif payload.task_type == "publish.request":
            PublishRequest.model_validate(payload.input)
    except Exception as exc:
        from pydantic import ValidationError
        if isinstance(exc, ValidationError):
            raise HTTPException(422, detail=exc.errors()) from None
        raise

    task = AgentTask(
        task_id=payload.task_id,
        task_type=payload.task_type,
        input_json=normalized_input,
        correlation_id=payload.correlation_id,
        status="queued",
    )
    db.add(task)
    try:
        db.commit()
    except Exception:
        db.rollback()
        existing = db.scalar(select(AgentTask).where(AgentTask.task_id == payload.task_id))
        if existing is None:
            raise HTTPException(500, "Could not persist agent task") from None
        if existing.task_type != payload.task_type or existing.input_json != normalized_input:
            raise HTTPException(409, "task_id concurrently created with different input") from None
        task = existing
    db.refresh(task)
    return {
        **_agent_task_summary(task),
        "status_url": "/api/v1/tasks/" + task.task_id,
        "idempotent_replay": False,
    }


@app.get("/api/v1/tasks/{task_id}", dependencies=[Depends(require_api_key)])
def get_agent_task(task_id: str, db: Session = Depends(get_db)):
    task = db.scalar(select(AgentTask).where(AgentTask.task_id == task_id))
    if task is None:
        raise HTTPException(404, "Agent task not found")
    return {
        **_agent_task_summary(task),
        "result": json.loads(task.result_json or "{}") if task.result_json else {},
    }


@app.get("/api/v1/tasks", dependencies=[Depends(require_api_key)])
def list_agent_tasks(db: Session = Depends(get_db), limit: int = 50):
    limit = max(1, min(limit, 100))
    rows = db.scalars(select(AgentTask).order_by(AgentTask.id.desc()).limit(limit)).all()
    return {"count": len(rows), "items": [_agent_task_summary(task) for task in rows]}


@app.post("/api/v1/tasks/{task_id}/cancel", dependencies=[Depends(require_api_key)])
def cancel_agent_task(
    task_id: str,
    payload: AgentTaskCancelRequest,
    db: Session = Depends(get_db),
):
    task = db.scalar(select(AgentTask).where(AgentTask.task_id == task_id))
    if task is None:
        raise HTTPException(404, "Agent task not found")
    if task.status != "queued":
        raise HTTPException(409, "Only queued tasks can be cancelled")
    result = db.execute(
        update(AgentTask)
        .where(AgentTask.id == task.id, AgentTask.status == "queued")
        .values(status="cancelled", error=payload.reason, updated_at=utcnow(), completed_at=utcnow())
    )
    db.commit()
    if result.rowcount != 1:
        raise HTTPException(409, "Task state changed; refresh before cancelling")
    db.refresh(task)
    return _agent_task_summary(task)
