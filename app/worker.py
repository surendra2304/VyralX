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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.migrations import run_additive_migrations
from app.models import AgentTask, Asset, PublishJob, RenderJob, Source, VideoProject, utcnow
from app.services.captions import write_srt
from app.services.media_quality import analyze_media_signals
from app.services.montage import render_montage
from app.services.peers import post_peer_json
from app.services.probe import probe_media
from app.services.project_pipeline import execute_project_pipeline
from app.services.renderer import render_video
from app.services.rights import (
    append_stock_attribution,
    find_repeat_use_blockers,
    source_is_publishable,
    verified_render_sources,
)
from app.services.task_dispatch import dispatch_agent_task
from app.services.youtube import (
    UploadOutcomeUnknown,
    clear_upload_session_checkpoint,
    clear_upload_success_checkpoint,
    load_upload_session_checkpoint,
    load_upload_success_checkpoint,
    upload_session_checkpoint_exists,
    upload_video,
)

settings = get_settings()
settings.prepare_directories()
Base.metadata.create_all(bind=engine)
run_additive_migrations(engine)
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("vyralx.worker")
UPLOAD_RESUME_BACKOFF_SECONDS = 30
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
    now = utcnow()
    resume_before = now - timedelta(seconds=UPLOAD_RESUME_BACKOFF_SECONDS)
    candidate = db.scalar(
        select(PublishJob.id)
        .where(
            or_(
                PublishJob.status == "queued",
                and_(
                    PublishJob.status == "resumable",
                    or_(
                        PublishJob.updated_at.is_(None),
                        PublishJob.updated_at <= resume_before,
                    ),
                ),
            )
        )
        .order_by(
            case(
                (PublishJob.status == "resumable", 0),
                (PublishJob.status == "queued", 1),
                else_=2,
            ),
            PublishJob.id.asc(),
        )
        .limit(1)
    )
    if candidate is None:
        return None
    candidate_status = db.scalar(
        select(PublishJob.status).where(PublishJob.id == candidate)
    )
    now = utcnow()
    result = db.execute(
        update(PublishJob)
        .where(
            PublishJob.id == candidate,
            PublishJob.status.in_(("queued", "resumable")),
        )
        .values(
            status="uploading",
            attempts=case(
                (PublishJob.status == "queued", PublishJob.attempts + 1),
                else_=PublishJob.attempts,
            ),
            started_at=case(
                (PublishJob.started_at.is_(None), now),
                else_=PublishJob.started_at,
            ),
            completed_at=None,
            updated_at=now,
            error="",
        )
    )
    db.commit()
    if result.rowcount != 1:
        return None
    claimed_id = int(candidate)
    if candidate_status == "queued":
        # A queued job is a new attempt. Stale receipts from a previous failed or
        # manually resolved attempt must not block session initialization.
        clear_upload_success_checkpoint(claimed_id)
        clear_upload_session_checkpoint(claimed_id)
    return claimed_id


def claim_agent_task(db: Session) -> int | None:
    candidate = db.scalar(
        select(AgentTask.id)
        .where(AgentTask.status == "queued")
        .order_by(
            case(
                (AgentTask.priority == "urgent", 0),
                (AgentTask.priority == "high", 1),
                (AgentTask.priority == "normal", 2),
                else_=3,
            ),
            AgentTask.id.asc(),
        )
        .limit(1)
    )
    if candidate is None:
        return None
    now = utcnow()
    result = db.execute(
        update(AgentTask)
        .where(AgentTask.id == candidate, AgentTask.status == "queued")
        .values(
            status="running",
            attempts=AgentTask.attempts + 1,
            started_at=now,
            updated_at=now,
            error="",
        )
    )
    db.commit()
    return int(candidate) if result.rowcount == 1 else None


def claim_video_project(db: Session) -> int | None:
    candidate = db.scalar(
        select(VideoProject.id)
        .where(VideoProject.status == "queued")
        .order_by(VideoProject.id.asc())
        .limit(1)
    )
    if candidate is None:
        return None
    now = utcnow()
    result = db.execute(
        update(VideoProject)
        .where(VideoProject.id == candidate, VideoProject.status == "queued")
        .values(
            status="running",
            attempts=VideoProject.attempts + 1,
            started_at=now,
            updated_at=now,
            error="",
        )
    )
    db.commit()
    return int(candidate) if result.rowcount == 1 else None


def process_video_project(project_id: int) -> None:
    with SessionLocal() as db:
        _heartbeat("busy", f"project:{project_id}")
        try:
            execute_project_pipeline(project_id, db)
        except Exception as exc:
            log.exception("Unexpected project worker failure project_id=%s", project_id)
            db.rollback()
            project = db.get(VideoProject, project_id)
            if project is not None:
                project.status = "failed"
                project.error = f"{type(exc).__name__}: {exc}"[:3000]
                project.completed_at = utcnow()
                project.updated_at = utcnow()
                db.commit()
        finally:
            _heartbeat("idle")


def process_agent_task(task_id: int) -> None:
    with SessionLocal() as db:
        task = db.get(AgentTask, task_id)
        if task is None:
            return
        _heartbeat("busy", f"task:{task.task_id}:{task.task_type}")
        try:
            if task.deadline:
                try:
                    deadline = datetime.fromisoformat(task.deadline.replace("Z", "+00:00"))
                except ValueError:
                    raise ValueError("deadline must be an ISO-8601 timestamp")
                if deadline.astimezone(timezone.utc) <= datetime.now(timezone.utc):
                    raise TimeoutError(f"Task deadline expired before execution ({task.deadline})")
            payload = json.loads(task.input_json or "{}")
            result = dispatch_agent_task(task.task_type, payload, db)
            task.result_json = json.dumps(result, ensure_ascii=False)
            task.status = "completed"
            task.error = ""
            log.info("Agent task completed task_id=%s task_type=%s", task.task_id, task.task_type)
        except Exception as exc:
            task.status = "failed"
            task.error = f"{type(exc).__name__}: {exc}"[:3000]
            if task.attempts < settings.worker_max_attempts:
                task.status = "queued"
                task.updated_at = utcnow()
            log.exception("Agent task failed task_row_id=%s", task_id)
        finally:
            task = db.get(AgentTask, task_id)
            if task is not None:
                task.completed_at = utcnow()
                task.updated_at = utcnow()
            db.commit()
            _heartbeat("idle")


def process_render_job(job_id: int) -> None:
    """Process a render job with bounded CPU/RAM resources and quality signal measurement."""
    with SessionLocal() as db:
        job = db.get(RenderJob, job_id)
        if job is None:
            return

        options = json.loads(job.options_json or "{}")
        montage_asset_ids = options.get("montage_asset_ids")

        if montage_asset_ids and isinstance(montage_asset_ids, list):
            # Dedicated multi-scene montage render
            assets = [db.get(Asset, aid) for aid in montage_asset_ids]
            if any(a is None for a in assets):
                job.status, job.error = "failed", "One or more montage asset records no longer exist"
                job.completed_at = utcnow()
                db.commit()
                return

            # Safety Invariant 2: Media Rights Verification Gate
            for a in assets:
                src = db.get(Source, a.source_id) if a.source_id else None
                if not a.rights_verified or not source_is_publishable(src):
                    job.status, job.error = "failed", f"Verified source license/permission record is required for asset {a.id}"
                    job.completed_at = utcnow()
                    db.commit()
                    return

            output = settings.render_dir / f"montage-job-{job.id}-{job.preset}.mp4"
            _heartbeat("busy", f"render:{job.id}")
            caption_path: Path | None = None
            try:
                segments = options.get("subtitle_segments") or []
                if segments:
                    caption_path = write_srt(segments, settings.data_dir / f"captions-job-{job.id}.srt")
                target_sec = int(options.get("target_seconds", 30))
                job.output_path = render_montage(
                    [a.file_path for a in assets],
                    output,
                    job.preset,
                    target_seconds=target_sec,
                    fit_mode=str(options.get("fit_mode", "pad")),
                    subtitle_file=caption_path,
                    voiceover_path=options.get("voiceover_path") or None,
                    cpu_threads=settings.render_max_cpu_threads,
                    max_memory_mb=settings.render_max_memory_mb,
                    normalize_loudness=True,
                    loudness_target_lufs=settings.render_audio_loudness_target_lufs,
                )
                try:
                    meta = probe_media(job.output_path)
                    sig = analyze_media_signals(
                        job.output_path,
                        ffmpeg_bin=settings.ffmpeg_bin,
                        actual_duration=float(meta.get("duration_seconds") or 0.0),
                        audio_stream_count=int(meta.get("audio_stream_count") or 0),
                    )
                    options["signal_analysis"] = sig
                    job.options_json = json.dumps(options, ensure_ascii=False)
                except Exception as probe_exc:
                    log.debug("Render signal scan skipped on montage: %s", probe_exc)
                job.status = "completed"
                job.error = ""
                log.info("Montage render completed job_id=%s scenes=%s preset=%s", job.id, len(assets), job.preset)
            except Exception as exc:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"[:3000]
                log.exception("Montage render failed job_id=%s", job.id)
                Path(output).unlink(missing_ok=True)
            finally:
                if caption_path is not None:
                    caption_path.unlink(missing_ok=True)
                job.completed_at = utcnow()
                job.updated_at = utcnow()
                db.commit()
                _heartbeat("idle")
            return

        # Single asset render
        asset = db.get(Asset, job.asset_id)
        if asset is None:
            job.status, job.error = "failed", "Asset record no longer exists"
            job.completed_at = utcnow()
            db.commit()
            return

        # Safety Invariant 2: Media Rights Verification Gate
        source = db.get(Source, asset.source_id) if asset.source_id else None
        if not asset.rights_verified or not source_is_publishable(source):
            job.status, job.error = "failed", "Verified source license/permission record is required"
            job.completed_at = utcnow()
            db.commit()
            return

        output = settings.render_dir / f"asset-{asset.id}-job-{job.id}-{job.preset}.mp4"
        _heartbeat("busy", f"render:{job.id}")
        caption_path = None
        try:
            segments = options.get("subtitle_segments") or []
            if segments:
                caption_path = write_srt(segments, settings.data_dir / f"captions-job-{job.id}.srt")
            job.output_path = render_video(
                asset.file_path,
                output,
                job.preset,
                trim_start_seconds=float(options.get("trim_start_seconds", 0)),
                trim_end_seconds=options.get("trim_end_seconds"),
                fit_mode=str(options.get("fit_mode", "pad")),
                subtitle_file=caption_path,
                voiceover_path=options.get("voiceover_path") or None,
                cpu_threads=settings.render_max_cpu_threads,
                max_memory_mb=settings.render_max_memory_mb,
                normalize_loudness=True,
                loudness_target_lufs=settings.render_audio_loudness_target_lufs,
            )
            # Probe result and scan signals before considering the job complete.
            try:
                meta = probe_media(job.output_path)
                sig = analyze_media_signals(
                    job.output_path,
                    ffmpeg_bin=settings.ffmpeg_bin,
                    actual_duration=float(meta.get("duration_seconds") or 0.0),
                    audio_stream_count=int(meta.get("audio_stream_count") or 0),
                )
                options["signal_analysis"] = sig
                job.options_json = json.dumps(options, ensure_ascii=False)
            except Exception as probe_exc:
                log.debug("Render signal scan skipped on asset render: %s", probe_exc)
            job.status = "completed"
            job.error = ""
            log.info("Render completed job_id=%s asset_id=%s preset=%s", job.id, asset.id, job.preset)
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"[:3000]
            log.exception("Render failed job_id=%s", job.id)
            Path(output).unlink(missing_ok=True)
        finally:
            if caption_path is not None:
                caption_path.unlink(missing_ok=True)
            job.completed_at = utcnow()
            job.updated_at = utcnow()
            db.commit()
            _heartbeat("idle")


def process_publish_job(job_id: int) -> None:
    """Process an approved publish job with quality verification and Sentinel policy audit."""
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

        # Safety Invariant 2: Media Rights Verification Gate
        if not asset.rights_verified or not source_is_publishable(source):
            job.status, job.error = "failed", "Verified source license/permission record is required"
            job.completed_at = utcnow()
            job.updated_at = utcnow()
            db.commit()
            return
        try:
            render_sources = verified_render_sources(render, db)
            repeat_use_blockers = find_repeat_use_blockers(
                render_sources, db, exclude_publish_job_id=job.id
            )
            if repeat_use_blockers:
                blocked_ids = ", ".join(
                    str(item["source_id"]) for item in repeat_use_blockers
                )
                raise ValueError(
                    "Repeat-use permission is not currently approved for previously published "
                    f"source ID(s): {blocked_ids}. Review the source evidence before publishing."
                )
            refreshed_description = append_stock_attribution(job.description, render_sources)
        except ValueError as exc:
            job.status, job.error = "failed", str(exc)[:3000]
            job.completed_at = utcnow()
            job.updated_at = utcnow()
            db.commit()
            return
        if refreshed_description != job.description:
            # Rights/source records may have changed after operator approval.
            # Never upload metadata that the operator has not seen and approved.
            job.description = refreshed_description
            job.status = "pending_approval"
            job.approved_at = None
            job.started_at = None
            job.completed_at = None
            job.attempts = max(0, job.attempts - 1)
            job.error = "Stock attribution changed after approval; review the updated description and approve again."
            job.updated_at = utcnow()
            db.commit()
            log.warning("Publish job returned for review because stock attribution changed job_id=%s", job.id)
            return

        _heartbeat("busy", f"publish:{job.id}")
        try:
            # Safety Invariant 3: Audio Loudness & Quality Standard
            signal_analysis = None
            actual_dur = 0.0
            audio_count = 0
            try:
                render_meta = probe_media(render.output_path)
                actual_dur = float(render_meta.get("duration_seconds") or 0.0)
                audio_count = int(render_meta.get("audio_stream_count") or 0)
                if actual_dur > 0:
                    signal_analysis = analyze_media_signals(
                        render.output_path,
                        ffmpeg_bin=settings.ffmpeg_bin,
                        actual_duration=actual_dur,
                        audio_stream_count=audio_count,
                    )
            except Exception as probe_err:
                log.debug("Media signal probe bypassed or unavailable: %s", probe_err)

            # If signal analysis ran on valid decoded media, enforce quality criteria
            if signal_analysis and signal_analysis.get("status") == "analyzed":
                black_intervals = signal_analysis.get("black_intervals") or []
                if black_intervals:
                    raise ValueError(
                        f"Safety Invariant 3 violation: {len(black_intervals)} black-frame intervals detected."
                    )
                silence_threshold = max(2.0, actual_dur * 0.08)
                long_silence = [
                    s for s in (signal_analysis.get("silence_intervals") or [])
                    if float(s.get("duration_seconds") or 0.0) > silence_threshold
                ]
                if long_silence:
                    raise ValueError(
                        f"Safety Invariant 3 violation: {len(long_silence)} long silence gaps detected."
                    )
                if audio_count > 0:
                    audio_metrics = signal_analysis.get("audio_metrics") or {}
                    loudness = audio_metrics.get("integrated_loudness_lufs")
                    if loudness is not None:
                        min_l = getattr(settings, "render_audio_loudness_min_lufs", -24.0)
                        max_l = getattr(settings, "render_audio_loudness_max_lufs", -10.0)
                        if not (min_l <= float(loudness) <= max_l):
                            raise ValueError(
                                f"Safety Invariant 3 violation: Audio loudness ({loudness} LUFS) "
                                f"is outside acceptable limits ({min_l} to {max_l} LUFS, target -14 LUFS)."
                            )

            # Peer Service Integration: Sentinel pre-publish policy verification (Objective 4)
            if settings.sentinel_required_for_publish:
                render_file = Path(render.output_path)
                file_hash = ""
                try:
                    import hashlib
                    file_hash = hashlib.sha256(render_file.read_bytes()).hexdigest()
                except Exception:
                    pass

                policy_request = {
                    "action": "youtube.publish",
                    "job_id": job.id,
                    "asset_id": asset.id,
                    "title": job.title,
                    "privacy_status": job.privacy_status,
                    "scheduled_at": job.scheduled_at or "",
                    "operator_review_acknowledged": job.approved_at is not None,
                    "rights_verified": bool(
                        asset.rights_verified
                        and source_is_publishable(source)
                        and render_sources
                        and all(
                            source_asset.rights_verified and source_is_publishable(source_record)
                            for source_asset, source_record in render_sources
                        )
                    ),
                }
                if "/security/audit" in settings.sentinel_policy_path:
                    policy_request["render_job_id"] = render.id
                    policy_request["media_metadata"] = {
                        "duration_seconds": actual_dur,
                        "audio_stream_count": audio_count,
                        "file_size": render_file.stat().st_size if render_file.is_file() else 0,
                        "sha256": file_hash,
                    }
                    policy_request["quality_scan"] = signal_analysis or {}
                policy = post_peer_json(
                    "sentinel",
                    settings.sentinel_policy_path,
                    policy_request,
                )
                allowed = policy.get("allowed") is True or policy.get("decision") in {"allow", "approved"}
                if not allowed:
                    reason = policy.get("reason") or "Sentinel policy did not explicitly allow this publish request"
                    raise RuntimeError(f"Sentinel policy audit denied publishing: {reason}")

            # Resumable YouTube Upload Flow (Objective 3 & Safety Invariant 1)
            video_id = upload_video(
                render.output_path,
                title=job.title,
                description=job.description,
                tags=json.loads(job.tags_json or "[]"),
                privacy_status=job.privacy_status,
                category_id=settings.youtube_category_id,
                scheduled_at=job.scheduled_at,
                publish_job_id=job.id,
                upload_attempt=job.attempts,
            )
            job.youtube_video_id = video_id
            job.status = "uploaded"
            job.error = ""
            log.info("YouTube upload completed job_id=%s video_id=%s", job.id, video_id)
        except UploadOutcomeUnknown as exc:
            session_state = load_upload_session_checkpoint(job.id, job.attempts)
            render_path = Path(render.output_path).resolve()
            can_resume = bool(
                session_state
                and render_path.is_file()
                and str(render_path) == session_state["file_path"]
                and render_path.stat().st_size == session_state["file_size"]
            )
            if can_resume:
                # upload_video probes the provider session and rechecks the content
                # hash before sending another chunk; this is not a blind retry.
                job.status = "resumable"
                job.error = (
                    "Upload paused with a saved YouTube session. The worker will verify provider "
                    "progress and resume the same attempt; if state no longer matches, it will "
                    "require manual reconciliation."
                )
                log.warning(
                    "YouTube upload paused with resumable session job_id=%s: %s",
                    job.id, str(exc)[:500],
                )
            else:
                job.status = "uncertain"
                job.error = str(exc)[:3000]
                log.error(
                    "YouTube upload outcome uncertain job_id=%s; manual reconciliation required",
                    job.id,
                )
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"[:3000]
            log.exception("YouTube upload failed job_id=%s", job.id)
        finally:
            job.completed_at = utcnow()
            job.updated_at = utcnow()
            db.commit()
            if job.status == "uploaded":
                clear_upload_success_checkpoint(job.id)
                clear_upload_session_checkpoint(job.id)
            _heartbeat("idle")


def recover_interrupted_jobs() -> dict[str, int]:
    """Recover confirmed uploads and never automatically repeat uncertain provider calls."""
    counts = {
        "renders": 0,
        "agent_tasks": 0,
        "projects": 0,
        "uploads_uncertain": 0,
        "uploads_recovered": 0,
        "uploads_resumable": 0,
    }
    with SessionLocal() as db:
        now = utcnow()
        render_jobs = db.scalars(select(RenderJob).where(RenderJob.status == "running")).all()
        for job in render_jobs:
            job.status = "failed"
            job.error = "Worker restarted during render; review the output and retry if needed."
            job.completed_at = now
            job.updated_at = now
            counts["renders"] += 1
        agent_tasks = db.scalars(select(AgentTask).where(AgentTask.status == "running")).all()
        for task in agent_tasks:
            task.status = "failed"
            task.error = "Worker restarted during task execution; submit a new task after reviewing side effects."
            task.completed_at = now
            task.updated_at = now
            counts["agent_tasks"] += 1
        projects = db.scalars(
            select(VideoProject).where(VideoProject.status.in_(("running", "rendering")))
        ).all()
        for project in projects:
            project.status = "failed"
            project.error = "Worker restarted while creating this project; review its stored scenes and retry."
            project.completed_at = now
            project.updated_at = now
            counts["projects"] += 1
        publish_jobs = db.scalars(select(PublishJob).where(PublishJob.status == "uploading")).all()
        completed_jobs: list[int] = []
        for job in publish_jobs:
            video_id = load_upload_success_checkpoint(job.id, job.attempts)
            if video_id:
                job.status = "uploaded"
                job.youtube_video_id = video_id
                job.error = ""
                job.completed_at = now
                job.updated_at = now
                completed_jobs.append(job.id)
                counts["uploads_recovered"] += 1
                continue

            session_state = load_upload_session_checkpoint(job.id, job.attempts)
            render = db.get(RenderJob, job.render_job_id)
            render_path = Path(render.output_path).resolve() if render and render.output_path else None
            media_still_matches = bool(
                session_state
                and render_path
                and render_path.is_file()
                and str(render_path) == session_state["file_path"]
                and render_path.stat().st_size == session_state["file_size"]
            )
            if media_still_matches:
                job.status = "resumable"
                job.error = (
                    "Worker restarted during a resumable YouTube upload. The worker will query "
                    "the saved provider session and resume only from the server-confirmed byte offset."
                )
                job.updated_at = now
                counts["uploads_resumable"] += 1
            else:
                job.status = "uncertain"
                if upload_session_checkpoint_exists(job.id):
                    reason = "saved upload-session checkpoint is missing, corrupt, stale or no longer matches the render"
                else:
                    reason = "no resumable upload session was saved"
                job.error = (
                    f"Worker restarted while uploading and {reason}. Check YouTube Studio/API state "
                    "before resolving; automatic new uploads are prohibited to prevent duplicates."
                )
                job.updated_at = now
                counts["uploads_uncertain"] += 1
        db.commit()
        for publish_job_id in completed_jobs:
            clear_upload_success_checkpoint(publish_job_id)
            clear_upload_session_checkpoint(publish_job_id)
    if any(counts.values()):
        log.warning("Recovered interrupted jobs: %s", counts)
    return counts


_queue_cursor = 0


def run_once() -> bool:
    """Claim one item with rotating priority so no durable queue is starved."""
    global _queue_cursor
    queue_names = ("agent", "project", "render", "publish")
    for offset in range(len(queue_names)):
        index = (_queue_cursor + offset) % len(queue_names)
        queue_name = queue_names[index]
        if queue_name == "agent":
            with SessionLocal() as db:
                job_id = claim_agent_task(db)
            processor = process_agent_task
        elif queue_name == "project":
            with SessionLocal() as db:
                job_id = claim_video_project(db)
            processor = process_video_project
        elif queue_name == "render":
            with SessionLocal() as db:
                job_id = claim_render_job(db)
            processor = process_render_job
        else:
            with SessionLocal() as db:
                job_id = claim_publish_job(db)
            processor = process_publish_job
        if job_id is not None:
            _queue_cursor = (index + 1) % len(queue_names)
            processor(job_id)
            return True
    return False


def main() -> None:
    global _stopping
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    log.info("VyralX worker started poll_seconds=%s", settings.worker_poll_seconds)
    recovery = recover_interrupted_jobs()
    _heartbeat("idle")
    log.info("Startup recovery complete: %s", recovery)
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
