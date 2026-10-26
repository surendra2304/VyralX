"""VyralX Cleanup: Removes embarrassing silent stock B-roll drafts from YouTube Studio.

STRICTLY PROTECTS:
- Video 1: sAymMXXCjFQ ("The $9,999,999 Michelin Restaurant")
- Video 2: 1C9CyiqW1kI ("Maximum Main Character Energy In School")
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.youtube import youtube_service

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [VyralX-Cleanup] %(message)s")
log = logging.getLogger("vyralx.cleanup")

PROTECTED_IDS = {"sAymMXXCjFQ", "1C9CyiqW1kI"}

BAD_STOCK_DRAFT_IDS = [
    "Kl_C7mZOUC0",  # High Speed Money Counting Machine
    "iQm8hNqQoSE",  # Glowing Fiber Optics
    "cJhhB9zxP-s",  # Kinetic Sand Clean Slicing
    "rA4YU2o4YJo",  # Billionaire Cash Counting
    "yS4NfHxiwlw",  # Suspect Under Interrogation Tension
    "CvmQ5rM4dlE",  # High Frequency Trading Server Racks
    "By3zfg8LGBw",  # Candlestick Trading Charts Collapse
    "UMxywB4E8cY",  # Microscopic Fluid Dynamics Reaction
    "aEwMVUziZ9o",  # Approaching Analog Clock
    "w7vvFjYqidw",  # Motion Video 41576
    "BoyQdb96ICI",  # Motion Video 41576 duplicate
    "oXgdIu2tG5A",  # Industrial Manufacturing Factory
]


def cleanup():
    yt = youtube_service()
    log.info("Starting cleanup of %d bad stock draft videos from YouTube...", len(BAD_STOCK_DRAFT_IDS))

    deleted_count = 0
    for vid in BAD_STOCK_DRAFT_IDS:
        if vid in PROTECTED_IDS:
            log.warning("PROTECTED: Skipping %s (User Master Video)", vid)
            continue
        try:
            yt.videos().delete(id=vid).execute()
            log.info("SUCCESS: Deleted bad draft from YouTube -> %s", vid)
            deleted_count += 1
        except Exception as err:
            log.warning("Could not delete %s (might already be deleted or invalid): %s", vid, err)

    # Clean up manifest
    manifest_path = Path("data/published_shorts_manifest.json")
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            cleaned = [
                item for item in data
                if (item.get("yt_id") in PROTECTED_IDS or item.get("youtube_id") in PROTECTED_IDS)
            ]
            manifest_path.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
            log.info("Manifest cleaned: preserved %d authentic master videos, removed all bad stock entries.", len(cleaned))
        except Exception as e:
            log.warning("Error updating manifest: %s", e)

    log.info("Cleanup complete: %d bad drafts deleted from YouTube Studio.", deleted_count)


if __name__ == "__main__":
    cleanup()
