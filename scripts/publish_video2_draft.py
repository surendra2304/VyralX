#!/usr/bin/env python3
"""Publish Video 2 in True 4K Master as DRAFT (private) with default video thumbnail."""
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
log = logging.getLogger("vyralx.publish_v2_draft")

VIDEO_FILE = Path("media/edited_videos/vyralx-commentary-hx265ujsLVU-4k-web.mp4").resolve()
TOKEN_FILE = Path("data/credentials/token.json").resolve()

TITLE = "Maximum Main Character Energy In School 💀✨ #Shorts"
DESCRIPTION = (
    "When you walk into high school thinking you are the anime main character... 💀😂\n\n"
    "💬 Rate this entrance from 1 to 10 in the comments below! 👇\n\n"
    "#Shorts #Comedy #Viral #MainCharacter #SchoolHumor #Relatable #VyralX"
)
TAGS = [
    "shorts", "comedy", "funny", "main character", "school humor",
    "viral comedy", "relatable", "trending shorts", "viral shorts", "parody", "vyralx"
]

def main():
    if not VIDEO_FILE.is_file():
        log.error("Video file does not exist: %s", VIDEO_FILE)
        sys.exit(1)

    log.info("Loading credentials from %s...", TOKEN_FILE)
    token_data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(token_data)
    service = build("youtube", "v3", credentials=creds, cache_discovery=False)

    log.info("Uploading Video 2 in 4K Master to DRAFTS (private): %s (%.2f MB)...", VIDEO_FILE.name, VIDEO_FILE.stat().st_size / (1024 * 1024))
    log.info("NO custom thumbnail will be set. Using default auto-generated video frame.")

    media = MediaFileUpload(
        str(VIDEO_FILE),
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024
    )

    request = service.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": TITLE,
                "description": DESCRIPTION,
                "tags": TAGS,
                "categoryId": "24",
                "defaultLanguage": "en",
                "defaultAudioLanguage": "en",
            },
            "status": {
                "privacyStatus": "private",  # Kept in Drafts for user review!
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
    log.info("SUCCESS! Video 2 saved to DRAFTS (private) with ID: %s -> %s", video_id, watch_url)
    print(f"\nDRAFT_4K_URL={watch_url}\n", flush=True)

if __name__ == "__main__":
    main()
