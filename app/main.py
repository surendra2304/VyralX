import json
import logging
import shutil
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.database import Base, engine, get_db
from app.migrations import run_additive_migrations
from app.models import Asset, ContentPack, PublishJob, RenderJob, Source, utcnow
from app.schemas import ContentGenerationRequest, DiscoveryRequest, PublishRequest, RenderRequest, SourceCreate
from app.security import require_api_key
from app.services.probe import probe_media
from app.services.discovery import discover_youtube_videos
from app.services.trends import rank_candidates
from app.services.content import generate_content_pack
from app.services.peers import configured_peers, peer_health, post_peer_json
from app.services.rights import source_is_publishable

settings = get_settings()
settings.prepare_directories()
Base.metadata.create_all(bind=engine)
run_additive_migrations(engine)
logging.basicConfig(level=settings.log_level)
log = logging.getLogger("vyralx")

app = FastAPI(title="VyralX", version="0.1.0",
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
    return {
        "status": "ready" if ready_state else "degraded",
        "database": "connected" if database_ok else "unavailable",
        "ffmpeg": ffmpeg_ok,
        "worker": worker_status,
    }


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
             "license_name": s.license_name, "rights_verified": s.rights_verified, "status": s.status}
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
    job = RenderJob(asset_id=asset.id, preset=payload.preset, status="queued")
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
             "output_path": j.output_path, "error": j.error} for j in rows]


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
            "note": "Queued only; call the execute endpoint to upload"}


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
    return [{"id": j.id, "asset_id": j.asset_id, "title": j.title, "status": j.status,
             "youtube_video_id": j.youtube_video_id, "error": j.error} for j in rows]
