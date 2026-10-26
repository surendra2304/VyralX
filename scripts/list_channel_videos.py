#!/usr/bin/env python3
"""List all videos currently uploaded to the VyralX YouTube channel."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.youtube import youtube_service

def list_videos():
    yt = youtube_service()
    channels = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    playlist_items = yt.playlistItems().list(playlistId=uploads_id, part="snippet,status", maxResults=50).execute()
    items = playlist_items.get("items", [])
    print(f"Total uploads on channel: {len(items)}")
    for item in items:
        vid = item["snippet"]["resourceId"]["videoId"]
        title = item["snippet"]["title"]
        status = item["status"]["privacyStatus"]
        print(f"VID: {vid} | STATUS: {status} | TITLE: {title}")

if __name__ == "__main__":
    list_videos()
