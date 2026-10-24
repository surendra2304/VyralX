#!/usr/bin/env python3
"""Update VyralX Channel SEO, Description, and Algorithmic Search Keywords."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from app.services.youtube import youtube_service

def main():
    service = youtube_service()
    resp = service.channels().list(part="id,brandingSettings", mine=True).execute()
    channel = resp["items"][0]
    channel_id = channel["id"]

    channel_desc = (
        "Welcome to VyralX — the ultimate hub for high-octane comedy shorts, hilarious commentary, "
        "and viral moments across the internet! 💀🔥\n\n"
        "🚀 Daily viral comedy shorts & relatable reactions.\n"
        "🔔 Hit Subscribe so you never miss the next drop!\n\n"
        "💼 Business & Sponsorship Inquiries: vyralx.creator@gmail.com"
    )

    channel_keywords = (
        '"comedy" "funny" "shorts" "viral" "memes" "humor" "entertainment" '
        '"reaction" "satire" "parody" "relatable" "trending shorts" "comedy shorts"'
    )

    update_body = {
        "id": channel_id,
        "brandingSettings": {
            "channel": {
                "title": "VyralX Agent",
                "description": channel_desc,
                "keywords": channel_keywords,
                "country": "US",
                "defaultLanguage": "en",
            }
        }
    }

    res = service.channels().update(part="brandingSettings", body=update_body).execute()
    print("SUCCESS! Channel brandingSettings and keywords updated successfully!")
    print("Updated description:\n", res["brandingSettings"]["channel"]["description"])
    print("Updated keywords:\n", res["brandingSettings"]["channel"]["keywords"])

if __name__ == "__main__":
    main()
