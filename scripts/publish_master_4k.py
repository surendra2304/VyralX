#!/usr/bin/env python3
"""Publish 4K Master with Google Official Resumable Uploader & Futuristic Thumbnail."""
import json
import logging
import os
import sys
import time
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vyralx.publish_master")

VIDEO_FILE = Path("media/edited_videos/vyralx-commentary-A_Q2qpbHrqo-4k-web.mp4").resolve()
THUMB_FILE = Path("media/edited_videos/vyralx-commentary-A_Q2qpbHrqo-thumbnail.jpg").resolve()
TOKEN_FILE = Path("data/credentials/token.json").resolve()

TITLE = "The $9,999,999 Michelin Restaurant 💀🧼 #Shorts"
DESCRIPTION = (
    "He dressed up in a luxury tuxedo for a 5-star Michelin dinner... but the waitress served him literal soap bubbles and blasted him with a bubble gun! 💀😂\n\n"
    "The final bill for this soap dinner? Exactly $9,999,999!\n\n"
    "💬 Would you pay the bill or run out of the restaurant? Drop your answer below! 👇\n\n"
    "#Shorts #Comedy #Viral #MichelinStar #FineDining #RichPeopleProblems #VyralX"
)
TAGS = [
    "shorts", "comedy", "funny", "michelin star", "fine dining",
    "viral comedy", "soap bubbles", "expensive restaurant", "relatable",
    "trending shorts", "viral shorts", "luxury dinner", "parody", "vyralx"
]

def main():
    if not VIDEO_FILE.is_file():
        log.error("Video file does not exist: %s", VIDEO_FILE)
        sys.exit(1)
    if not THUMB_FILE.is_file():
        log.error("Thumbnail file does not exist: %s", THUMB_FILE)
        sys.exit(1)

    log.info("Loading credentials from %s...", TOKEN_FILE)
    token_data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(token_data)
    service = build("youtube", "v3", credentials=creds, cache_discovery=False)

    log.info("Starting Resumable 4K Master upload: %s (%.2f MB)...", VIDEO_FILE.name, VIDEO_FILE.stat().st_size / (1024 * 1024))
    
    media = MediaFileUpload(
        str(VIDEO_FILE),
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024  # 1MB chunk for steady progress & no timeouts
    )

    request = service.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": TITLE,
                "description": DESCRIPTION,
                "tags": TAGS,
                "categoryId": "24",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            }
        },
        media_body=media
    )

    response = None
    last_reported = -1
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            if pct != last_reported:
                log.info("Upload progress: %d%% (%d / %d MB)", pct, int(status.resumable_progress / (1024 * 1024)), int(status.total_size / (1024 * 1024)))
                last_reported = pct

    video_id = response.get("id")
    watch_url = f"https://youtube.com/shorts/{video_id}"
    log.info("SUCCESS! Video published with ID: %s -> %s", video_id, watch_url)

    # Attach futuristic thumbnail
    log.info("Attaching brand-new futuristic thumbnail: %s...", THUMB_FILE.name)
    try:
        service.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(THUMB_FILE), mimetype="image/jpeg", resumable=True)
        ).execute()
        log.info("SUCCESS! Futuristic thumbnail attached to video: %s", video_id)
    except Exception as e:
        log.error("Failed to attach thumbnail: %s", e)

    # Write manifest
    manifest_path = Path("data/published_shorts_manifest.json")
    manifest_data = [{
        "video_id": "A_Q2qpbHrqo",
        "yt_id": video_id,
        "title": TITLE,
        "watch_url": watch_url,
        "quality": "4K UHD (2160x3840 @ 60fps)",
        "thumbnail": str(THUMB_FILE),
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "published"
    }]
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    log.info("Saved manifest to %s", manifest_path)
    print(f"\nFINAL_LIVE_URL={watch_url}\n", flush=True)

if __name__ == "__main__":
    main()
