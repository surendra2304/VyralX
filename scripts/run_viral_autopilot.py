"""Autonomous VyralX viral channel driver.

Each cycle it:

1. reads the Shorts tabs of the five creators behind the channel's first four
   uploads, then YouTube's recommendation graph rooted at those exact clips, and
   keeps only clips that already prove view potential in the channel's lanes;
2. auditions each candidate's audio: a silent clip gets fresh commentary, a
   narrated clip keeps its own audio and gets transcript subtitles (never two
   voices on top of each other);
3. edits it into the channel format (1080x1920, impact subtitles, genre
   thumbnail) and records the rights/attribution record;
4. hands the queued publish job to the normal worker, which runs the rights,
   silence and loudness gates before uploading **unlisted**.

    python scripts/run_viral_autopilot.py            # one cycle
    python scripts/run_viral_autopilot.py --loop     # run the channel forever
    python scripts/run_viral_autopilot.py --discover-only
"""
from __future__ import annotations

import argparse
import json
import logging
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings, get_settings
from app.database import Base, SessionLocal, engine
from app.migrations import run_additive_migrations
from app.services.viral_discovery import (
    discover_candidates,
    discover_candidates_api,
    used_source_video_ids,
)
from app.services.viral_remix import produce_viral_short
from app.services.ytdlp_support import cookies_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("vyralx.viral_autopilot")

# Auditioning is expensive (download + Whisper), so a candidate that is rejected
# on its merits must not come back on the next cycle. Without this ledger the
# pool is re-ranked identically every run and the same narrated clip is
# re-downloaded forever, starving the channel of uploads.
_REJECT_LEDGER = Path(__file__).resolve().parents[1] / "data" / "rejected_sources.json"
_REJECT_LIMIT = 500

# Failures that say nothing about the clip itself: a retry may succeed once the
# network, the cookie jar or the render host recovers.
_TRANSIENT_REASONS = {
    "audio_unavailable",
    "download_failed",
    "render_failed",
    "tts_failed",
    "upload_failed",
    "timeout",
}


def _load_rejections() -> dict[str, dict]:
    try:
        raw = json.loads(_REJECT_LEDGER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _rejected_ids() -> set[str]:
    return {str(key) for key in _load_rejections()}


def _record_rejection(video_id: str, reason: str) -> None:
    """Persist a permanent rejection so the pool advances on the next cycle."""
    if not video_id or str(reason).lower() in _TRANSIENT_REASONS:
        return
    data = _load_rejections()
    data[str(video_id)] = {
        "reason": str(reason),
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if len(data) > _REJECT_LIMIT:
        newest = sorted(data.items(), key=lambda item: item[1].get("at", ""))[-_REJECT_LIMIT:]
        data = dict(newest)
    try:
        _REJECT_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        staging = _REJECT_LEDGER.with_suffix(".json.tmp")
        staging.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        staging.replace(_REJECT_LEDGER)
    except OSError as exc:
        log.warning("Could not persist rejection for %s: %s", video_id, exc)


def bootstrap() -> Settings:
    settings = get_settings()
    settings.prepare_directories()
    Path(settings.render_dir).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    run_additive_migrations(engine)
    try:
        from app.media_store import bootstrap_media_schema

        bootstrap_media_schema()
    except Exception as exc:  # media warehouse is optional
        log.info("Media warehouse bootstrap skipped: %s", exc)
    return settings


def produce_one(settings: Settings, *, max_candidates: int) -> dict:
    if not cookies_file():
        # Every source download goes through yt-dlp, and YouTube refuses
        # datacenter IPs without a signed-in jar. Fail fast with a clear reason
        # instead of auditioning candidates that cannot be fetched.
        log.warning(
            "No YouTube cookie jar found (%s); source downloads cannot work on this host",
            getattr(settings, "youtube_cookies_file", "./data/youtube_cookies.txt"),
        )
        return {"status": "NO_COOKIES"}
    with SessionLocal() as db:
        used = used_source_video_ids(db)
        rejected = _rejected_ids()
        pool_kwargs = dict(
            limit=12,
            exclude_ids=used | rejected,
            min_views=int(getattr(settings, "viral_min_source_views", 1_000_000)),
            max_seconds=float(getattr(settings, "viral_max_source_seconds", 58)),
            min_seconds=float(getattr(settings, "viral_min_source_seconds", 12)),
        )
        # The Data API is the primary path: it answers in seconds, costs a
        # handful of quota units, and is not subject to the browser bot wall or
        # to yt-dlp's per-channel JS challenge solves.
        candidates = []
        try:
            candidates = discover_candidates_api(**pool_kwargs)
        except Exception as exc:
            log.warning("API discovery failed: %s", exc)
        if not candidates and cookies_file():
            log.info("Data API found nothing; falling back to yt-dlp discovery")
            candidates = discover_candidates(
                seed_ids=set(list(used)[-4:]) if used else None,
                **pool_kwargs,
            )
        if not candidates:
            return {"status": "NO_CANDIDATES"}

        attempts: list[dict] = []
        for candidate in candidates[: max(1, max_candidates)]:
            log.info(
                "Trying %s | %.1fs | %s views | score %.2f | %s",
                candidate.video_id, candidate.duration, candidate.view_count,
                candidate.score, candidate.title[:70],
            )
            result = produce_viral_short(candidate, db, publish=True)
            attempts.append(result)
            if result.get("status") in {"QUEUED_FOR_PUBLISH", "RENDERED"}:
                return {"status": "PRODUCED", "result": result, "attempts": attempts}
            reason = str(result.get("reason") or result.get("status") or "unknown")
            _record_rejection(candidate.video_id, reason)
            log.info("Skipped %s: %s", candidate.video_id, reason)
        return {"status": "ALL_CANDIDATES_REJECTED", "attempts": attempts}


def drain_publish_queue(timeout_seconds: int = 1800) -> dict:
    from app.worker import run_once

    started = time.time()
    uploaded = 0
    idle = 0
    while time.time() - started < timeout_seconds:
        if run_once():
            uploaded += 1
            idle = 0
            continue
        idle += 1
        if idle >= 3:
            break
        time.sleep(2)
    return {"jobs_processed": uploaded, "seconds": round(time.time() - started, 1)}


def report(limit: int = 5) -> None:
    from sqlalchemy import select

    from app.models import PublishJob

    with SessionLocal() as db:
        jobs = db.scalars(select(PublishJob).order_by(PublishJob.id.desc()).limit(limit)).all()
        for job in jobs:
            log.info(
                "publish id=%s status=%s privacy=%s video=https://youtu.be/%s error=%s",
                job.id, job.status, job.privacy_status, job.youtube_video_id or "-",
                (job.error or "")[:200],
            )


def run_cycle(settings: Settings, args: argparse.Namespace) -> dict:
    produced = produce_one(
        settings,
        max_candidates=args.max_candidates,
    )
    log.info("Production step: %s", produced.get("status"))
    if produced.get("status") != "PRODUCED":
        return produced
    log.info("Edit mode: %s", produced["result"].get("edit_mode"))
    log.info("Queued publish job: %s", produced["result"].get("publish_job_id"))
    drained = drain_publish_queue(timeout_seconds=args.timeout)
    log.info("Queue drain: %s", drained)
    report()
    return produced


def _acquire_single_instance_lock() -> socket.socket | None:
    """Hold a localhost port for the life of the loop so only one runs."""
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", 8765))
        lock.listen(1)
    except OSError:
        lock.close()
        return None
    return lock


def main() -> None:
    parser = argparse.ArgumentParser(description="VyralX autonomous viral channel driver")
    parser.add_argument("--loop", action="store_true", help="run cycles forever")
    parser.add_argument("--interval", type=int, default=0, help="minutes between cycles (default: settings)")
    parser.add_argument("--max-candidates", type=int, default=10, help="candidates to audition per cycle")
    parser.add_argument("--timeout", type=int, default=1800, help="max seconds per publish drain")
    parser.add_argument("--allow-narrated", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--discover-only", action="store_true", help="print ranked candidates and exit")
    args = parser.parse_args()

    settings = bootstrap()
    log.info(
        "Viral autopilot: channel=%s privacy=%s source-policy=%s",
        settings.channel_name or "(unset)",
        settings.autonomous_publish_privacy,
        getattr(settings, "viral_source_policy", "transformative"),
    )

    if args.discover_only:
        with SessionLocal() as db:
            candidates = discover_candidates(limit=12, exclude_ids=used_source_video_ids(db))
        for candidate in candidates:
            log.info(
                "%.2f | %ss | %s views | %s | %s",
                candidate.score, int(candidate.duration), candidate.view_count,
                candidate.category, candidate.title[:80],
            )
        return

    # Every mode takes the lock: the timer fires a one-shot cycle, and a manual
    # cycle running at the same time would double the render load on a 2-vCPU
    # host and race the same candidate into two publish jobs.
    lock = _acquire_single_instance_lock()
    if lock is None:
        log.error("Another autopilot cycle is already running; exiting.")
        return

    if not args.loop:
        run_cycle(settings, args)
        return

    log.info("Autopilot loop lock acquired (127.0.0.1:8765)")

    interval = max(10, args.interval or settings.autonomous_run_interval_minutes)
    while True:
        try:
            run_cycle(settings, args)
        except Exception:
            log.exception("Cycle failed; continuing")
        log.info("Sleeping %d minutes", interval)
        time.sleep(interval * 60)


if __name__ == "__main__":
    main()
