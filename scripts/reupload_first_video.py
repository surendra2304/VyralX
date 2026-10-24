#!/usr/bin/env python3
"""Re-upload the 1st approved benchmark short to VyralX YouTube channel."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ["YOUTUBE_UPLOAD_ENABLED"] = "true"

from app.services.youtube import upload_video, youtube_credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vyralx.reupload")

VIDEO = {
    "id": "A_Q2qpbHrqo",
    "file": "media/edited_videos/vyralx-commentary-A_Q2qpbHrqo.mp4",
    "thumbnail": "media/edited_videos/vyralx-commentary-A_Q2qpbHrqo-thumbnail.jpg",
    "title": "The $9,999,999 Michelin Restaurant 💀🧼 #Shorts",
    "description": (
        "He dressed up in a luxury tuxedo for a 5-star Michelin dinner... but the waitress served him literal soap bubbles and blasted him with a bubble gun! 💀😂\n\n"
        "The final bill for this soap dinner? Exactly $9,999,999!\n\n"
        "💬 Would you pay the bill or run out of the restaurant? Drop your answer below! 👇\n\n"
        "💼 Business & Sponsorship Inquiries: vyralx.creator@gmail.com\n\n"
    ),
    "tags": [
        "shorts", "comedy", "funny", "michelin star", "fine dining",
        "viral comedy", "soap bubbles", "expensive restaurant", "relatable",
        "trending shorts", "viral shorts", "luxury dinner", "parody"
    ],
    "category_id": "24",
}


def main():
    vpath = Path(VIDEO["file"]).resolve()
    tpath = Path(VIDEO["thumbnail"]).resolve()

    if not vpath.is_file():
        log.error("Video file not found: %s", vpath)
        sys.exit(1)

    log.info("Uploading 1st benchmark short: '%s' (%.2f MB)...", VIDEO["title"], vpath.stat().st_size / (1024 * 1024))
    
    yt_id = upload_video(
        file_path=str(vpath),
        title=VIDEO["title"],
        description=VIDEO["description"],
        tags=VIDEO["tags"],
        privacy_status="public",
        category_id=VIDEO["category_id"],
    )
    watch_url = f"https://youtube.com/shorts/{yt_id}"
    log.info("SUCCESS! Published '%s' -> %s", VIDEO["title"], watch_url)

    if tpath.is_file():
        try:
            creds = youtube_credentials()
            service = build("youtube", "v3", credentials=creds, cache_discovery=False)
            service.thumbnails().set(
                videoId=yt_id,
                media_body=MediaFileUpload(str(tpath), mimetype="image/jpeg", resumable=True),
            ).execute()
            log.info("SUCCESS! Custom thumbnail attached to video: %s", yt_id)
        except Exception as th_err:
            log.warning("Thumbnail upload optional fallback: %s", th_err)

    # Update manifest
    manifest_path = Path("data/published_shorts_manifest.json")
    manifest_data = [{
        "video_id": VIDEO["id"],
        "yt_id": yt_id,
        "title": VIDEO["title"],
        "watch_url": watch_url,
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "published"
    }]
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    log.info("Saved manifest to %s", manifest_path)
    print(f"\nNEW_YOUTUBE_URL={watch_url}\n", flush=True)


if __name__ == "__main__":
    main()
