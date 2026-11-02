"""Autonomous VyralX production driver.

Queues one original, on-niche project from the channel profile, then drains the
durable render/publish queue using the same worker used in production. Run it once
for a single cycle, or with ``--loop`` to keep producing at
``AUTONOMOUS_RUN_INTERVAL_MINUTES``.

    python scripts/run_autopilot.py            # one cycle
    python scripts/run_autopilot.py --loop     # continuous
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time

from app.config import Settings, get_settings
from app.database import Base, engine
from app.migrations import run_additive_migrations
from app.media_store import bootstrap_media_schema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("vyralx.autopilot")


def _bootstrap() -> Settings:
    settings = get_settings()
    settings.prepare_directories()
    Base.metadata.create_all(bind=engine)
    run_additive_migrations(engine)
    try:
        bootstrap_media_schema()
    except Exception as exc:  # media warehouse is optional in development
        log.warning("Media warehouse bootstrap skipped: %s", exc)
    return settings


async def _queue_one_project() -> dict:
    from app.services.autonomous_orchestrator import AutonomousChannelOrchestrator

    orchestrator = AutonomousChannelOrchestrator()
    plan = await orchestrator.generate_weekly_plan()
    due = plan.due_videos()
    candidates = due if due else [(idea, None) for idea in plan.ideas]
    if not candidates:
        return {"status": "NO_IDEA", "message": "No content idea could be produced"}
    last: dict = {}
    for idea, _when in candidates:
        last = await orchestrator.produce_video(idea)
        log.info("Queue result: %s", last)
        if last.get("status") in {"QUEUED_FOR_PRODUCTION", "QUEUE_ERROR"}:
            break
        if last.get("status") in {"AWAITING_OPERATOR_CONFIGURATION", "AWAITING_LICENSE_CONFIRMATION"}:
            break
    return last


def _drain_queue(timeout_seconds: int = 3600, idle_polls: int = 5) -> dict:
    """Process worker jobs until the queue stays empty for a few consecutive polls."""
    from app.worker import run_once

    started = time.time()
    idle = 0
    processed = 0
    while time.time() - started < timeout_seconds:
        worked = run_once()
        if worked:
            processed += 1
            idle = 0
            continue
        idle += 1
        if idle >= idle_polls:
            break
        time.sleep(2)
    return {"processed": processed, "seconds": round(time.time() - started, 1)}


def _report_tail(limit: int = 5) -> None:
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import PublishJob, RenderJob, VideoProject

    with SessionLocal() as db:
        projects = db.scalars(select(VideoProject).order_by(VideoProject.id.desc()).limit(limit)).all()
        for p in projects:
            render = db.get(RenderJob, p.render_job_id) if p.render_job_id else None
            log.info(
                "project id=%s status=%s error=%s render=%s",
                p.id, p.status, (p.error or "")[:200],
                (render.output_path if render else None),
            )
        jobs = db.scalars(select(PublishJob).order_by(PublishJob.id.desc()).limit(limit)).all()
        for j in jobs:
            log.info(
                "publish id=%s status=%s privacy=%s video=%s error=%s",
                j.id, j.status, j.privacy_status, j.youtube_video_id, (j.error or "")[:300],
            )


def run_cycle() -> None:
    queued = asyncio.run(_queue_one_project())
    log.info("Autonomous queue step: %s", queued)
    result = _drain_queue()
    log.info("Queue drain: %s", result)
    _report_tail()


def main() -> None:
    parser = argparse.ArgumentParser(description="VyralX autonomous production driver")
    parser.add_argument("--loop", action="store_true", help="keep producing on the configured interval")
    parser.add_argument("--timeout", type=int, default=3600, help="max seconds per queue drain")
    args = parser.parse_args()

    settings = _bootstrap()
    log.info(
        "Autopilot start: channel=%s auto_publish=%s privacy=%s interval=%smin",
        settings.channel_name or "(unset)",
        settings.autonomous_auto_publish,
        settings.autonomous_publish_privacy,
        settings.autonomous_run_interval_minutes,
    )
    if not args.loop:
        run_cycle()
        return
    while True:
        try:
            queued = asyncio.run(_queue_one_project())
            log.info("Autonomous queue step: %s", queued)
            log.info("Queue drain: %s", _drain_queue(timeout_seconds=args.timeout))
            _report_tail()
        except Exception:
            log.exception("Autopilot cycle failed; continuing")
        time.sleep(max(60, settings.autonomous_run_interval_minutes * 60))


if __name__ == "__main__":
    main()
