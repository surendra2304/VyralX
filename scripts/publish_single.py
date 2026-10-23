import os
import sys
import json
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure YOUTUBE_UPLOAD_ENABLED is true
os.environ["YOUTUBE_UPLOAD_ENABLED"] = "true"

from app.services.autonomous_pipeline import VideoJob, publish_or_stage

def main():
    job = VideoJob(
        video_id="8kggT2ej-lo",
        source_file=Path("media/viral_sources/8kggT2ej-lo.mp4"),
        title_concept="MrBeast Sent Him On A Real Safari! 🦓🐆 #Shorts",
        script=(
            "MrBeast took a fan out of his bedroom and dropped him right into the middle of the African savannah. "
            "From watching towering giraffes up close to seeing wild leopards lounging on the grass, "
            "that is the ultimate dream trip."
        ),
        cyan_keywords={"MRBEAST", "FAN", "AFRICAN", "SAVANNAH", "GIRAFFES", "LEOPARDS", "ULTIMATE", "TRIP"},
        category_id="24",
        debate_question="Would you go on an African safari with MrBeast? YES or NO? 👇",
        tags=["shorts", "mrbeast", "safari", "animals", "wildlife", "africa"]
    )

    rendered_video = Path("media/edited_videos/vyralx-commentary-8kggT2ej-lo.mp4")
    if not rendered_video.exists():
        print(f"Error: {rendered_video} not found on disk")
        return

    print(f"Publishing {rendered_video} ({rendered_video.stat().st_size / (1024*1024):.2f} MB)...")
    res = publish_or_stage(job, rendered_video)
    print("UPLOAD RESULT:", json.dumps(res, indent=2))

    if res.get("status") in ("published", "staged_quota_limited"):
        manifest_path = Path("data/published_shorts_manifest.json")
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
        except Exception:
            data = []
        data.append(res)
        manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print("Updated published manifest.")

if __name__ == "__main__":
    main()
