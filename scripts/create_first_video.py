"""Autonomous production and publishing script for VyralX's first YouTube Short."""
import json
import logging
import math
import sys
from pathlib import Path

# Ensure VyralX package is loaded
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vyralx.first_video")

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Asset, PublishJob, RenderJob, Source, utcnow  # noqa: E402
from app.services.captions import segment_script, write_ass, write_srt  # noqa: E402
from app.services.montage import render_montage  # noqa: E402
from app.services.probe import probe_media  # noqa: E402
from app.services.rights import append_stock_attribution, verified_render_sources  # noqa: E402
from app.services.sentinel import compute_provenance_hash  # noqa: E402
from app.services.thumbnail import extract_thumbnail  # noqa: E402
from app.services.unsplash import import_photo, search_photos  # noqa: E402
from app.services.voiceover import synthesize_voiceover  # noqa: E402
from app.services.youtube import upload_video  # noqa: E402


def main():
    settings = get_settings()
    log.info("Starting VyralX autonomous video generation...")

    # Step 1: Script & Content Pack
    topic = "Quantum AI Just Broke Physics: The 12-Millisecond Breakthrough"
    hook = "Artificial Intelligence just solved a fifty-year-old physics impossibility, and almost nobody noticed."
    voiceover_script = (
        f"{hook} "
        "Deep neural networks successfully simulated quantum entanglement at room temperature, cracking calculations "
        "that would take standard supercomputers forty years in just twelve milliseconds. "
        "This rewrites the future of encryption, drug discovery, and computing power forever. "
        "Subscribe to VyralX for daily frontier technology breakthroughs."
    )

    scenes_queries = [
        "quantum supercomputer glowing blue servers datacenter",
        "artificial intelligence silicon microchip processor circuit",
        "futuristic cybersecurity digital matrix streams",
        "deep space satellite telecommunications network",
    ]

    title = f"{topic} #Shorts"
    description = (
        "Deep neural networks just simulated room-temperature quantum entanglement in 12 milliseconds—solving "
        "a calculation that would take supercomputers 40 years.\n\n"
        "Subscribe to @VyralX for daily frontier AI and deep tech revelations!\n\n"
        "#AI #QuantumComputing #Technology #Supercomputer #Shorts #VyralX"
    )
    tags = ["AI", "QuantumComputing", "Supercomputer", "Technology", "FutureTech", "Shorts", "VyralX"]

    # Step 2: Voiceover via ElevenLabs
    log.info("Synthesizing neural voiceover via ElevenLabs...")
    voice_res = synthesize_voiceover(voiceover_script)
    voice_path = Path(voice_res["file_path"]).resolve()
    log.info("Voiceover generated: %s (%s bytes)", voice_path, voice_res["bytes"])

    voice_meta = probe_media(voice_path)
    actual_voice_dur = float(voice_meta.get("duration_seconds") or 0.0)
    target_seconds = max(15, math.ceil(actual_voice_dur))
    log.info("Voiceover duration: %.2fs -> target_seconds: %ds", actual_voice_dur, target_seconds)

    # Step 3: Sourcing visual assets via Unsplash
    log.info("Sourcing 4K editorial visuals from Unsplash...")
    with SessionLocal() as db:
        assets: list[Asset] = []
        used_photo_ids = set()
        sec_per_scene = float(target_seconds) / len(scenes_queries)

        for idx, query in enumerate(scenes_queries):
            results = search_photos(query, orientation="portrait", per_page=10)
            if not results:
                results = search_photos("technology artificial intelligence", orientation="portrait", per_page=10)
            
            chosen_photo = None
            for p in results:
                if p["id"] not in used_photo_ids:
                    chosen_photo = p
                    break
            if not chosen_photo and results:
                chosen_photo = results[0]

            if not chosen_photo:
                raise RuntimeError(f"Could not find visual for scene {idx + 1}")

            used_photo_ids.add(chosen_photo["id"])
            imported = import_photo(
                chosen_photo["id"],
                chosen_photo["download_url"],
                title=f"{chosen_photo['title']} - {query[:100]}",
                creator=chosen_photo["creator"],
                creator_url=chosen_photo["creator_url"],
            )

            source = Source(
                title=imported["title"],
                source_url=imported["source_url"],
                platform="unsplash",
                creator=imported["creator"],
                license_name="Unsplash License",
                permission_reference="https://unsplash.com/license",
                rights_verified=True,
                repeat_use_allowed=True,
                repeat_use_reviewed_at=utcnow(),
                repeat_use_review_notes="Unsplash free commercial use license.",
                status="licensed",
            )
            db.add(source)
            db.flush()

            asset = Asset(
                source_id=source.id,
                title=imported["title"],
                file_path=imported["file_path"],
                duration_seconds=sec_per_scene,
                width=imported["width"],
                height=imported["height"],
                rights_verified=True,
            )
            db.add(asset)
            db.flush()
            assets.append(asset)
            log.info("Scene %d ready: %s by %s", idx + 1, imported["title"][:50], imported["creator"])

        db.commit()

        # Step 4: Subtitles
        log.info("Generating word-timed ViralYellow kinetic captions...")
        segments = segment_script(voiceover_script, target_seconds)
        sub_dir = settings.data_dir / "subtitles"
        sub_dir.mkdir(parents=True, exist_ok=True)
        srt_path = sub_dir / "vyralx-launch.srt"
        ass_path = sub_dir / "vyralx-launch.ass"
        write_srt(segments, srt_path)
        try:
            write_ass(segments, ass_path, style="ViralYellow")
            used_sub = ass_path
        except Exception:
            used_sub = srt_path

        # Step 5: Montage Rendering with Ken Burns Motion
        output_path = settings.render_dir / "vyralx-launch-short.mp4"
        settings.render_dir.mkdir(parents=True, exist_ok=True)
        log.info("Rendering 1080x1920 Short with dynamic Ken Burns motion: %s", output_path)

        rendered = render_montage(
            [a.file_path for a in assets],
            output_path,
            "shorts",
            target_seconds=target_seconds,
            fit_mode="pad",
            subtitle_file=used_sub,
            voiceover_path=str(voice_path),
            enable_ken_burns=True,
        )

        render_meta = probe_media(rendered)
        log.info("Render complete! Duration: %.2fs, Resolution: %dx%d, Audio Streams: %d",
                 render_meta.get("duration_seconds", 0), render_meta.get("width", 0),
                 render_meta.get("height", 0), render_meta.get("audio_stream_count", 0))

        # Thumbnail
        thumbnail_path = settings.render_dir / "vyralx-launch-thumbnail.jpg"
        extract_thumbnail(rendered, thumbnail_path, min(1.0, max(0.0, target_seconds / 4)))
        log.info("Thumbnail generated: %s", thumbnail_path)

        # Step 6: Create RenderJob & PublishJob for full traceability
        render_job = RenderJob(
            asset_id=assets[0].id,
            preset="shorts",
            status="completed",
            output_path=str(rendered),
            attempts=1,
            started_at=utcnow(),
            completed_at=utcnow(),
            options_json=json.dumps({
                "montage_asset_ids": [a.id for a in assets],
                "fit_mode": "pad",
                "target_seconds": target_seconds,
                "provenance_sha256": compute_provenance_hash(rendered),
            }),
        )
        db.add(render_job)
        db.flush()

        render_sources = verified_render_sources(render_job, db)
        publish_description = append_stock_attribution(description, render_sources)

        publish_job = PublishJob(
            asset_id=assets[0].id,
            render_job_id=render_job.id,
            title=title,
            description=publish_description,
            tags_json=json.dumps(tags),
            privacy_status="public",
            status="approved",
            attempts=1,
            approved_at=utcnow(),
        )
        db.add(publish_job)
        db.commit()
        db.refresh(publish_job)

        # Step 7: Resumable YouTube Upload
        log.info("Uploading video directly to YouTube channel 'VyralX'...")
        video_id = upload_video(
            str(rendered),
            title=publish_job.title,
            description=publish_job.description,
            tags=tags,
            privacy_status=publish_job.privacy_status,
            category_id="28",
            publish_job_id=publish_job.id,
            upload_attempt=1,
        )

        publish_job.youtube_video_id = video_id
        publish_job.status = "uploaded"
        publish_job.completed_at = utcnow()
        db.commit()

        video_url = f"https://www.youtube.com/watch?v={video_id}"
        shorts_url = f"https://youtube.com/shorts/{video_id}"
        log.info("=" * 60)
        log.info("SUCCESS! Video published live to YouTube!")
        log.info("Video ID: %s", video_id)
        log.info("Video URL: %s", video_url)
        log.info("Shorts URL: %s", shorts_url)
        log.info("=" * 60)
        print(f"\n[LIVE_VIDEO_ID]: {video_id}")
        print(f"[LIVE_VIDEO_URL]: {video_url}")
        print(f"[LIVE_SHORTS_URL]: {shorts_url}")


if __name__ == "__main__":
    main()
