#!/usr/bin/env python3
"""Re-upload the 1st approved benchmark short in True 8K with the brand-new futuristic thumbnail."""
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
log = logging.getLogger("vyralx.reupload_8k")

OLD_VIDEO_ID = "jKTfeLPYZl0"

VIDEO = {
    "id": "A_Q2qpbHrqo",
    "file_8k": "media/edited_videos/vyralx-commentary-A_Q2qpbHrqo-8k.mp4",
    "file_4k": "media/edited_videos/vyralx-commentary-A_Q2qpbHrqo-4k.mp4",
    "thumbnail": "media/edited_videos/vyralx-commentary-A_Q2qpbHrqo-thumbnail.jpg",
    "title": "The $9,999,999 Michelin Restaurant 💀🧼 #Shorts",
    "description": (
        "He dressed up in a luxury tuxedo for a 5-star Michelin dinner... but the waitress served him literal soap bubbles and blasted him with a bubble gun! 💀😂\n\n"
        "The final bill for this soap dinner? Exactly $9,999,999!\n\n"
        "💬 Would you pay the bill or run out of the restaurant? Drop your answer below! 👇\n\n"
        "#Shorts #Comedy #Viral #MichelinStar #FineDining #RichPeopleProblems #VyralX"
    ),
    "tags": [
        "shorts", "comedy", "funny", "michelin star", "fine dining",
        "viral comedy", "soap bubbles", "expensive restaurant", "relatable",
        "trending shorts", "viral shorts", "luxury dinner", "parody", "vyralx"
    ],
    "category_id": "24",
}


def delete_old_video(service, video_id: str):
    try:
        log.info("Deleting old video: %s...", video_id)
        service.videos().delete(id=video_id).execute()
        log.info("Successfully deleted old video: %s", video_id)
    except Exception as exc:
        log.warning("Could not delete old video %s: %s", video_id, exc)


def main():
    creds = youtube_credentials()
    service = build("youtube", "v3", credentials=creds, cache_discovery=False)

    # 1. Delete previous version
    delete_old_video(service, OLD_VIDEO_ID)

    # 2. Prefer 8K if present and complete, else fallback to 4K
    p_8k = Path(VIDEO["file_8k"]).resolve()
    p_4k = Path(VIDEO["file_4k"]).resolve()
    tpath = Path(VIDEO["thumbnail"]).resolve()

    target_video = p_8k if p_8k.is_file() else p_4k
    if not target_video.is_file():
        log.error("Neither 8K nor 4K video file found!")
        sys.exit(1)

    log.info("Uploading Master video: '%s' (%s, %.2f MB)...", VIDEO["title"], target_video.name, target_video.stat().st_size / (1024 * 1024))
    
    yt_id = upload_video(
        file_path=str(target_video),
        title=VIDEO["title"],
        description=VIDEO["description"],
        tags=VIDEO["tags"],
        privacy_status="public",
        category_id=VIDEO["category_id"],
    )
    watch_url = f"https://youtube.com/shorts/{yt_id}"
    log.info("SUCCESS! Published '%s' -> %s", VIDEO["title"], watch_url)

    # 3. Set the new futuristic thumbnail
    if tpath.is_file():
        try:
            log.info("Attaching brand-new futuristic thumbnail: %s...", tpath)
            service.thumbnails().set(
                videoId=yt_id,
                media_body=MediaFileUpload(str(tpath), mimetype="image/jpeg", resumable=True),
            ).execute()
            log.info("SUCCESS! Futuristic thumbnail attached to video: %s", yt_id)
        except Exception as th_err:
            log.error("Thumbnail upload failed: %s", th_err)

    # 4. Update manifest
    manifest_path = Path("data/published_shorts_manifest.json")
    manifest_data = [{
        "video_id": VIDEO["id"],
        "yt_id": yt_id,
        "title": VIDEO["title"],
        "watch_url": watch_url,
        "quality": "8K UHD (4320x7680)" if target_video == p_8k else "4K UHD (2160x3840)",
        "thumbnail": str(tpath),
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "published"
    }]
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    log.info("Saved manifest to %s", manifest_path)
    print(f"\nNEW_YOUTUBE_URL={watch_url}\n", flush=True)


if __name__ == "__main__":
    main()
