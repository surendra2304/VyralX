"""Verify the publish chain for an already-rendered project without a new render."""
import json
from app.config import get_settings
from app.database import SessionLocal
from app.models import PublishJob, RenderJob, VideoProject, utcnow
from app.worker import process_publish_job

settings = get_settings()
with SessionLocal() as db:
    import sys
    project = db.get(VideoProject, int(sys.argv[1]) if len(sys.argv) > 1 else 37)
    render = db.get(RenderJob, project.render_job_id)
    asset_id = json.loads(project.asset_ids_json)[0]
    job = PublishJob(
        asset_id=asset_id,
        render_job_id=render.id,
        title=(project.topic[:90] + " #Shorts"),
        description="Verification run.\n\nSubscribe to VyralX for daily deep tech breakdowns.",
        tags_json=json.dumps(["AI", "technology", "VyralX"]),
        privacy_status=settings.autonomous_publish_privacy,
        status="queued",
        approved_at=utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id
    print("created publish job", job_id, "privacy", job.privacy_status)

process_publish_job(job_id)

with SessionLocal() as db:
    job = db.get(PublishJob, job_id)
    print("FINAL status:", job.status)
    print("FINAL video:", job.youtube_video_id)
    print("FINAL error:", (job.error or "")[:400])
