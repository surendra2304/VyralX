"""Real-time YouTube Channel Creation Watcher & Automated Publisher.

Polls Google YouTube API to detect when the user initializes their YouTube channel.
As soon as the channel entity is active, it automatically publishes all queued
viral repurposed videos directly to YouTube Shorts!
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.config import get_settings
from app.database import SessionLocal
from app.models import PublishJob, RenderJob, utcnow
from app.services.youtube import upload_video

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [Channel-Watcher] %(message)s")
log = logging.getLogger("vyralx.watcher")


def check_channel_ready() -> bool:
    """Check if the user's Google account has created a YouTube channel."""
    settings = get_settings()
    token_file = settings.data_dir / "credentials" / "token.json"
    if not token_file.is_file():
        return False

    with open(token_file) as f:
        tdata = json.load(f)

    creds = Credentials(
        token=tdata.get("token"),
        refresh_token=tdata.get("refresh_token"),
        token_uri=tdata.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=tdata.get("client_id"),
        client_secret=tdata.get("client_secret"),
        scopes=tdata.get("scopes"),
    )

    yt = build("youtube", "v3", credentials=creds)
    sample_file = next(Path("media/viral_sources").glob("*.mp4"), None)
    if not sample_file or not sample_file.is_file():
        return False

    body = {"snippet": {"title": "Ping", "categoryId": "28"}, "status": {"privacyStatus": "private"}}
    media = MediaFileUpload(str(sample_file), mimetype="video/mp4", resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    try:
        req.execute()
        return True
    except Exception as e:
        err_str = str(e)
        if "youtubeSignupRequired" in err_str or "Unauthorized" in err_str:
            return False
        # If the channel exists, it will succeed or give another error (e.g. quota, title, etc.)
        log.info("Channel entity response: %s", err_str[:120])
        return True


def flush_pending_uploads():
    """Upload all pending/failed viral jobs to YouTube."""
    with SessionLocal() as db:
        failed_jobs = (
            db.query(PublishJob)
            .filter(PublishJob.status == "failed")
            .order_by(PublishJob.id.desc())
            .all()
        )
        log.info("Found %d pending publish jobs to upload...", len(failed_jobs))
        uploaded_count = 0
        for job in failed_jobs:
            render_job = db.query(RenderJob).filter(RenderJob.id == job.render_job_id).first()
            if not render_job or not Path(render_job.output_path).is_file():
                continue
            try:
                log.info("Publishing job %d ('%s') to YouTube...", job.id, job.title)
                yt_id = upload_video(
                    render_job.output_path,
                    title=job.title,
                    description=job.description,
                    tags=json.loads(job.tags_json or "[]"),
                    privacy_status=job.privacy_status or "private",
                    category_id="24",
                    publish_job_id=job.id,
                    upload_attempt=1,
                )
                job.status = "uploaded"
                job.youtube_video_id = yt_id
                job.completed_at = utcnow()
                job.error = None
                db.commit()
                uploaded_count += 1
                log.info("PUBLISHED! Link: https://youtu.be/%s", yt_id)
            except Exception as e:
                log.error("Failed uploading job %d: %s", job.id, e)
                db.rollback()

        log.info("Flush completed: %d videos successfully published to YouTube!", uploaded_count)


def watch_and_publish_loop(poll_interval: int = 15):
    """Continuously poll until channel is active, then flush all uploads."""
    log.info("Watching for YouTube channel creation (polling every %ds)...", poll_interval)
    while True:
        try:
            if check_channel_ready():
                log.info("YOUTUBE CHANNEL IS LIVE! Flushing queued viral videos...")
                flush_pending_uploads()
                break
            else:
                log.info("Still waiting for channel creation. Please click 'Create a channel' on youtube.com...")
        except Exception as e:
            log.warning("Watcher check warning: %s", e)
        time.sleep(poll_interval)


if __name__ == "__main__":
    watch_and_publish_loop(15)
