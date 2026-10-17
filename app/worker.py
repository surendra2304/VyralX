"""Durable database-backed worker for render and approved publish jobs.

Run as a separate process/container: python -m app.worker
The API and worker share the database and media volumes. Jobs survive restarts.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.migrations import run_additive_migrations
from app.models import Asset, PublishJob, RenderJob, Source, utcnow
from app.services.probe import probe_media
from app.services.renderer import render_video
from app.services.rights import source_is_publishable
from app.services.youtube import upload_video

settings = get_settings()
settings.prepare_directories()
Base.metadata.create_all(bind=engine)
run_additive_migrations(engine)
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("vyralx.worker")
_stopping = False


def _handle_stop(signum: int, _frame: object) -> None:
    global _stopping
    log.info("Shutdown requested (signal=%s); finishing current job", signum)
    _stopping = True


def _heartbeat(state: str, current_job: str | None = None) -> None:
    path = settings.data_dir / "worker-heartbeat.json"
    payload = {
        "service": "vyralx-worker",
        "state": state,
        "job": current_job,
        "pid": os.getpid(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload), encoding="utf-8")
    temp.replace(path)


def claim_render_job(db: Session) -> int | None:
    candidate = db.scalar(
        select(RenderJob.id)
        .where(RenderJob.status == "queued")
        .order_by(RenderJob.id.asc())
        .limit(1)
    )
    if candidate is None:
        return None
    now = utcnow()
    result = db.execute(
        update(RenderJob)
        .where(RenderJob.id == candidate, RenderJob.status == "queued")
        .values(
            status="running",
            attempts=RenderJob.attempts + 1,
            started_at=now,
            updated_at=now,
            error="",
        )
    )
    db.commit()
    return int(candidate) if result.rowcount == 1 else None


def claim_publish_job(db: Session) -> int | None:
    candidate = db.scalar(
        select(PublishJob.id)
        .where(PublishJob.status == "queued")
        .order_by(PublishJob.id.asc())
        .limit(1)
    )
    if candidate is None:
        return None
    now = utcnow()
    result = db.execute(
        update(PublishJob)
        .where(PublishJob.id == candidate, PublishJob.status == "queued")
        .values(
            status="uploading",
            attempts=PublishJob.attempts + 1,
            started_at=now,
            updated_at=now,
            error="",
        )
    )
    db.commit()
    return int(candidate) if result.rowcount == 1 else None


def process_render_job(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(RenderJob, job_id)
        if job is None:
            return
        asset = db.get(Asset, job.asset_id)
        if asset is None:
            job.status, job.error = "failed", "Asset record no longer exists"
            job.completed_at = utcnow()
            db.commit()
            return
        source = db.get(Source, asset.source_id) if asset.source_id else None
        if not asset.rights_verified or not source_is_publishable(source):
            job.status, job.error = "failed", "Verified source license/permission record is required"
            job.completed_at = utcnow()
            db.commit()
            return
        output = settings.render_dir / (
            f"asset-{asset.id}-job-{job.id}-{job.preset}.mp4"
        )
        _heartbeat("busy", f"render:{job.id}")
        try:
            job.output_path = render_video(asset.file_path, output, job.preset)
            # Probe the result before considering the job complete.
            probe_media(job.output_path)
            job.status = "completed"
            job.error = ""
            log.info("Render completed job_id=%s asset_id=%s preset=%s", job.id, asset.id, job.preset)
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"[:3000]
            log.exception("Render failed job_id=%s", job.id)
            Path(output).unlink(missing_ok=True)
        finally:
            job.completed_at = utcnow()
            job.updated_at = utcnow()
            db.commit()
            _heartbeat("idle")


def process_publish_job(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(PublishJob, job_id)
        if job is None:
            return
        asset = db.get(Asset, job.asset_id)
        render = db.get(RenderJob, job.render_job_id)
        source = db.get(Source, asset.source_id) if asset and asset.source_id else None
        if (
            asset is None or render is None or render.asset_id != asset.id
            or render.status != "completed" or not Path(render.output_path).is_file()
        ):
            job.status, job.error = "failed", "The selected completed render is missing"
            job.completed_at = utcnow()
            job.updated_at = utcnow()
            db.commit()
            return
        if not asset.rights_verified or not source_is_publishable(source):
            job.status, job.error = "failed", "Verified source license/permission record is required"
            job.completed_at = utcnow()
            job.updated_at = utcnow()
            db.commit()
            return
        _heartbeat("busy", f"publish:{job.id}")
        try:
            video_id = upload_video(
                render.output_path,
                title=job.title,
                description=job.description,
                tags=json.loads(job.tags_json or "[]"),
                privacy_status=job.privacy_status,
                category_id=settings.youtube_category_id,
                scheduled_at=job.scheduled_at,
            )
            job.youtube_video_id = video_id
            job.status = "uploaded"
            job.error = ""
            log.info("YouTube upload completed job_id=%s video_id=%s", job.id, video_id)
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"[:3000]
            log.exception("YouTube upload failed job_id=%s", job.id)
        finally:
            job.completed_at = utcnow()
            job.updated_at = utcnow()
            db.commit()
            _heartbeat("idle")


def run_once() -> bool:
    """Claim at most one job; render jobs are prioritized over uploads."""
    with SessionLocal() as db:
        render_id = claim_render_job(db)
    if render_id is not None:
        process_render_job(render_id)
        return True
    with SessionLocal() as db:
        publish_id = claim_publish_job(db)
    if publish_id is not None:
        process_publish_job(publish_id)
        return True
    return False


def main() -> None:
    global _stopping
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    log.info("VyralX worker started poll_seconds=%s", settings.worker_poll_seconds)
    _heartbeat("idle")
    while not _stopping:
        try:
            worked = run_once()
            if not worked:
                _heartbeat("idle")
                time.sleep(max(0.5, settings.worker_poll_seconds))
        except Exception:
            log.exception("Worker loop error; will continue")
            _heartbeat("degraded")
            time.sleep(max(1, settings.worker_poll_seconds))
    _heartbeat("stopped")
    log.info("VyralX worker stopped cleanly")


if __name__ == "__main__":
    main()
