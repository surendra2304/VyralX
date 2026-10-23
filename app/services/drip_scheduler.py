"""VyralX Drip Scheduler & Publication Velocity Engine.

Schedules publications across optimal circadian algorithmic peaks (8:30 AM, 2:00 PM, 8:00 PM),
spaces out upload quotas, and monitors daily quota reset times.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import SessionLocal
from app.models import PublishJob, RenderJob, VideoProject, utcnow

log = logging.getLogger("vyralx.drip_scheduler")

# Optimal publication windows (UTC)
OPTIMAL_HOURS_UTC = [3, 8, 14, 19]  # 8:30 AM IST, 1:30 PM IST, 7:30 PM IST, 12:30 AM IST


def compute_next_drip_slots(count: int = 5, start_time: datetime | None = None) -> list[datetime]:
    """Compute future spaced release timestamps aligned with optimal viral viewer spikes."""
    current = start_time or datetime.now(timezone.utc)
    slots: list[datetime] = []
    
    # Check next 7 days
    day_offset = 0
    while len(slots) < count and day_offset < 7:
        target_day = (current + timedelta(days=day_offset)).date()
        for hour in OPTIMAL_HOURS_UTC:
            candidate = datetime(target_day.year, target_day.month, target_day.day, hour, 0, tzinfo=timezone.utc)
            if candidate > current and candidate not in slots:
                slots.append(candidate)
                if len(slots) >= count:
                    break
        day_offset += 1

    return slots


def get_queued_publication_schedule() -> list[dict[str, Any]]:
    """Fetch unreleased rendered jobs and map them to their scheduled drip slots."""
    with SessionLocal() as db:
        pending_jobs = (
            db.query(PublishJob)
            .filter(PublishJob.status.in_(["pending", "failed"]))
            .order_by(PublishJob.id.asc())
            .all()
        )

        slots = compute_next_drip_slots(count=len(pending_jobs))
        schedule = []
        for job, slot in zip(pending_jobs, slots):
            render = db.query(RenderJob).filter(RenderJob.id == job.render_job_id).first()
            schedule.append({
                "publish_job_id": job.id,
                "title": job.title,
                "render_file": render.output_path if render else "unknown",
                "scheduled_slot_utc": slot.isoformat(),
                "scheduled_slot_ist": (slot + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %I:%M %p IST"),
                "status": job.status,
            })

        return schedule
