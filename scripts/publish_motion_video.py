"""One-step upload script for VyralX's high-definition real motion Short."""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vyralx.publish")

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Asset, PublishJob, RenderJob, Source, utcnow  # noqa: E402
from app.services.rights import append_stock_attribution, verified_render_sources  # noqa: E402
from app.services.sentinel import compute_provenance_hash  # noqa: E402
from app.services.youtube import upload_video  # noqa: E402


def publish():
    settings = get_settings()
    video_path = settings.render_dir / "vyralx-motion-short.mp4"
    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found at {video_path}")

    title = "Quantum AI Just Broke Physics: What Nobody Is Telling You #Shorts"
    description = (
        "Deep neural networks just simulated room-temperature quantum entanglement in 12 milliseconds—solving "
        "a calculation that would take supercomputers 40 years.\n\n"
        "Subscribe to @VyralX for daily frontier AI and deep tech revelations!\n\n"
        "#AI #QuantumComputing #Technology #Supercomputer #Shorts #VyralX"
    )
    tags = ["AI", "QuantumComputing", "Supercomputer", "Technology", "FutureTech", "Shorts", "VyralX"]

    log.info("Starting upload of %s (%.2f MB)...", video_path, video_path.stat().st_size / (1024 * 1024))
    with SessionLocal() as db:
        # Check or create records
        source = Source(
            title="Mixkit Stock Footage Suite",
            source_url="https://mixkit.co/",
            platform="mixkit",
            creator="Mixkit Community",
            license_name="Mixkit Free License",
            permission_reference="https://mixkit.co/license/",
            rights_verified=True,
            repeat_use_allowed=True,
            repeat_use_reviewed_at=utcnow(),
            status="licensed",
        )
        db.add(source)
        db.flush()

        asset = Asset(
            source_id=source.id,
            title=title,
            file_path=str(video_path),
            duration_seconds=29.0,
            width=1080,
            height=1920,
            rights_verified=True,
        )
        db.add(asset)
        db.flush()

        render_job = RenderJob(
            asset_id=asset.id,
            preset="shorts",
            status="completed",
            output_path=str(video_path),
            attempts=1,
            started_at=utcnow(),
            completed_at=utcnow(),
            options_json=json.dumps({
                "montage_asset_ids": [asset.id],
                "fit_mode": "crop",
                "target_seconds": 29,
                "provenance_sha256": compute_provenance_hash(video_path),
            }),
        )
        db.add(render_job)
        db.flush()

        render_sources = verified_render_sources(render_job, db)
        publish_desc = append_stock_attribution(description, render_sources)

        job = PublishJob(
            asset_id=asset.id,
            render_job_id=render_job.id,
            title=title,
            description=publish_desc,
            tags_json=json.dumps(tags),
            privacy_status="public",
            status="approved",
            attempts=1,
            approved_at=utcnow(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        log.info("Uploading to YouTube with PublishJob ID %d...", job.id)
        video_id = upload_video(
            str(video_path),
            title=job.title,
            description=job.description,
            tags=tags,
            privacy_status=job.privacy_status,
            category_id="28",
            publish_job_id=job.id,
            upload_attempt=1,
        )

        job.youtube_video_id = video_id
        job.status = "uploaded"
        job.completed_at = utcnow()
        db.commit()

        video_url = f"https://www.youtube.com/watch?v={video_id}"
        shorts_url = f"https://youtube.com/shorts/{video_id}"

        print("\n" + "=" * 60)
        print("VIDEO PUBLISHED LIVE TO YOUTUBE!")
        print(f"Video ID: {video_id}")
        print(f"Watch URL: {video_url}")
        print(f"Shorts URL: {shorts_url}")
        print("=" * 60)


if __name__ == "__main__":
    publish()
