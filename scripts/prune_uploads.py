"""Delete specific uploads from the channel (operator cleanup tool).

Used to remove an off-brand or truncated upload so the channel only carries
videos that match the first-four format.

    python scripts/prune_uploads.py IeGv6LPZo2E g1rHqvTUpxQ
    python scripts/prune_uploads.py --dry-run g1rHqvTUpxQ
"""
from __future__ import annotations

import argparse
import logging

from app.services.youtube import youtube_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vyralx.prune")


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete uploads by YouTube video id")
    parser.add_argument("video_ids", nargs="+", help="video ids to delete")
    parser.add_argument("--dry-run", action="store_true", help="show what would be deleted")
    args = parser.parse_args()

    service = youtube_service()
    for video_id in args.video_ids:
        video_id = video_id.strip()
        if not video_id:
            continue
        try:
            detail = service.videos().list(part="snippet,status", id=video_id).execute()
        except Exception as exc:
            log.error("%s: lookup failed (%s)", video_id, exc)
            continue
        items = detail.get("items") or []
        if not items:
            log.warning("%s: not found on this channel", video_id)
            continue
        item = items[0]
        title = (item.get("snippet") or {}).get("title", "")
        privacy = (item.get("status") or {}).get("privacyStatus", "")
        if args.dry_run:
            log.info("%s would be deleted | %s | %s", video_id, privacy, title[:70])
            continue
        try:
            service.videos().delete(id=video_id).execute()
            log.info("%s deleted | %s | %s", video_id, privacy, title[:70])
        except Exception as exc:
            log.error("%s: delete failed (%s)", video_id, exc)


if __name__ == "__main__":
    main()
