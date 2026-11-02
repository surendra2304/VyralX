"""Queue and render one project directly, then report silence + QA gates."""
import json
import subprocess
import sys
import uuid

from app.config import get_settings
from app.database import Base, engine, SessionLocal
from app.models import ContentPack, RenderJob, VideoProject, utcnow
from app.services.project_pipeline import execute_project_pipeline

settings = get_settings()
settings.prepare_directories()
Base.metadata.create_all(bind=engine)

topic = sys.argv[1] if len(sys.argv) > 1 else "The Race to Build Self-Improving AI"

with SessionLocal() as db:
    project = VideoProject(
        project_key="verify-" + uuid.uuid4().hex[:10],
        topic=topic,
        video_format="shorts",
        target_seconds=45,
        audience="general audience",
        tone="clear, energetic and factual",
        scene_count=3,
        confirm_pexels_license=True,
        confirm_pexels_repeat_use=True,
        use_voiceover=True,
        status="queued",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    pid = project.id
    print("queued project", pid, "topic:", topic)
    execute_project_pipeline(pid, db)
    db.refresh(project)
    print("status:", project.status, "error:", (project.error or "")[:300])
    if project.render_job_id:
        render = db.get(RenderJob, project.render_job_id)
        path = render.output_path
        print("render:", path)
        r = subprocess.run(
            [settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-i", path,
             "-af", "silencedetect=noise=-35dB:d=0.5", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        for line in r.stderr.splitlines():
            if "silence_duration" in line or "Duration:" in line:
                print("  ", line)
        pack = json.loads(db.get(ContentPack, project.content_pack_id).pack_json)
        qa = pack.get("production_qa", {})
        print("qa status:", qa.get("status"), "passed:", qa.get("passed_count"), "warnings:", qa.get("warning_count"))
        for check in qa.get("checks", []):
            if not check.get("passed", True):
                print("  FAILED CHECK:", check)
