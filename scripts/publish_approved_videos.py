"""VyralX Publisher for Approved Transformed Shorts.

Publishes both perfected commentary shorts to YouTube with high-CTR viral titles,
SEO-rich descriptions, engagement discussion prompts, and targeted search tags.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.youtube import upload_video  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vyralx.publisher")

UPLOADS = [
    {
        "id": "A_Q2qpbHrqo",
        "file": "media/edited_videos/vyralx-commentary-A_Q2qpbHrqo.mp4",
        "title": "The $9,999,999 Michelin Restaurant 💀🧼 #Shorts",
        "description": (
            "He dressed up in a luxury tuxedo for a 5-star Michelin dinner... but the waitress served him literal soap bubbles and blasted him with a bubble gun! 💀😂\n\n"
            "The final bill for this soap dinner? Exactly $9,999,999!\n\n"
            "💬 Would you pay the bill or run out of the restaurant? Drop your answer below! 👇\n\n"
            "#Shorts #Comedy #Funny #MichelinStar #FineDining #Viral #Humor #Relatable #Trending #Memes #Reels"
        ),
        "tags": [
            "shorts", "comedy", "funny", "michelin star", "fine dining",
            "viral comedy", "soap bubbles", "expensive restaurant", "relatable",
            "trending shorts", "viral shorts", "luxury dinner", "parody"
        ],
        "category_id": "24",  # Entertainment
    },
    {
        "id": "hx265ujsLVU",
        "file": "media/edited_videos/vyralx-commentary-hx265ujsLVU.mp4",
        "title": "Maximum Main Character Energy In School 💅💀 #Shorts",
        "description": (
            "When your friends try to roast you in the hallway, but you have 1000% main character energy! 💅✨\n\n"
            "She delivered the cleanest, most unimpressed eye-roll on the internet and turned the hallway into Paris Fashion Week. 0% hesitation, 100% unbothered.\n\n"
            "💬 On a scale of 1-10, how savage was that eye-roll? Tag that one friend who has this exact energy! 👇\n\n"
            "#Shorts #MainCharacter #SchoolHumor #Attitude #Relatable #Viral #Trending #Funny #FashionWeek #Savage #Reels"
        ),
        "tags": [
            "shorts", "main character", "attitude", "school humor", "relatable",
            "unbothered", "eye roll", "viral shorts", "trending shorts", "comedy",
            "savage", "high school", "confidence"
        ],
        "category_id": "24",  # Entertainment
    },
]

def publish_all():
    log.info("Starting publication of %d approved commentary shorts...", len(UPLOADS))
    results = []

    for idx, item in enumerate(UPLOADS, 1):
        vpath = Path(item["file"])
        if not vpath.is_file():
            log.error("Video file not found: %s", vpath)
            continue

        log.info("[%d/%d] Uploading: '%s' (%s, %.2f MB)...",
                 idx, len(UPLOADS), item["title"], vpath.name, vpath.stat().st_size / (1024 * 1024))
        try:
            yt_id = upload_video(
                file_path=str(vpath),
                title=item["title"],
                description=item["description"],
                tags=item["tags"],
                privacy_status="public",
                category_id=item["category_id"],
            )
            watch_url = f"https://youtube.com/shorts/{yt_id}"
            log.info("SUCCESS! Published '%s' -> %s", item["title"], watch_url)
            results.append({
                "video_id": item["id"],
                "yt_id": yt_id,
                "title": item["title"],
                "watch_url": watch_url,
                "status": "published"
            })
            time.sleep(3)
        except Exception as e:
            log.exception("Upload failed for %s: %s", vpath.name, e)
            results.append({
                "video_id": item["id"],
                "error": str(e),
                "status": "failed"
            })

    output_summary = Path("data/published_shorts_manifest.json")
    output_summary.parent.mkdir(parents=True, exist_ok=True)
    output_summary.write_text(json.dumps(results, indent=2), encoding="utf-8")
    log.info("Publication manifest saved to %s", output_summary)
    return results

if __name__ == "__main__":
    publish_all()
