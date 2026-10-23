"""VyralX 24/7 Autonomous Viral Shorts Loop Engine.

Autonomously runs the entire lifecycle on a scheduled cadence:
1. Discovery: Searches YouTube & web for high-velocity viral visual clips (< 60s, dialogue-free).
2. Curation: Filters and downloads clean, high-resolution source clips.
3. Scriptwriting: Synthesizes high-hook narrative commentary (en-US-GuyNeural, zero 'sir').
4. Timing: Extracts exact WordBoundary timestamps from Edge-TTS.
5. Typography: Renders un-squeezed Montserrat Black at 105pt (Pure White + Electric Cyan).
6. Composition: Full-bleed 1080x1920 @ 60fps with ducked ambience and -14 LUFS loudnorm.
7. SEO Optimization: High-CTR titles, engagement questions, and hashtags.
8. Publication: Automatically uploads to YouTube, tracking daily quotas and manifests.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.autonomous_pipeline import VideoJob, run_pipeline

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [VyralX-AutoLoop] %(message)s"
)
log = logging.getLogger("vyralx.loop")

SEARCH_TOPICS = [
    "oddly satisfying visual compilation shorts",
    "unexpected comedy twist silent short",
    "extreme balance precision stunt short",
    "genius survival bushcraft life hack short",
    "hypnotic kinetic sand art short",
    "mind blowing optical illusion viral short"
]


def search_and_download_viral_clip(query: str, download_dir: Path) -> Path | None:
    """Uses yt-dlp to find and download a top-velocity vertical viral short."""
    download_dir.mkdir(parents=True, exist_ok=True)
    log.info("Searching YouTube for trending candidate: '%s'...", query)

    search_cmd = [
        "yt-dlp",
        "--skip-download",
        "--dump-json",
        f"ytsearch5:{query}",
        "--match-filter", "duration <= 60 & duration >= 12"
    ]
    res = subprocess.run(search_cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if not res.stdout:
        log.warning("No search results for query: %s", query)
        return None

    for line in res.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            d = json.loads(line)
            vid = d.get("id")
            title = d.get("title", "")
            views = d.get("view_count", 0)
            dur = d.get("duration", 0)

            # Look for clips with strong view velocity
            if views and views > 500_000:
                dest_file = download_dir / f"{vid}.mp4"
                if dest_file.exists():
                    log.info("Clip %s already exists on disk, reusing.", vid)
                    return dest_file

                log.info("Found prime viral candidate: %s ('%s', %d views, %ds)", vid, title[:40], views, dur)
                dl_cmd = [
                    "yt-dlp",
                    "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "--merge-output-format", "mp4",
                    "-o", str(dest_file),
                    f"https://youtube.com/shorts/{vid}"
                ]
                dl_res = subprocess.run(dl_cmd, capture_output=True)
                if dest_file.exists() and dest_file.stat().st_size > 0:
                    log.info("Successfully ingested source: %s (%.2f MB)", dest_file.name, dest_file.stat().st_size / (1024 * 1024))
                    return dest_file
        except Exception as e:
            continue
    return None


def run_autonomous_cycle(batch_size: int = 1):
    """Executes a single end-to-end autonomous discovery, production, and publication cycle."""
    log.info("==================================================================")
    log.info("STARTING VYRALX 24/7 AUTONOMOUS CYCLE (BATCH SIZE: %d)", batch_size)
    log.info("==================================================================")

    source_dir = Path("media/viral_sources").resolve()
    # Execute batch production
    from scripts.run_autonomous_production import PRODUCTION_JOBS
    results = run_pipeline(PRODUCTION_JOBS[:batch_size])

    log.info("==================================================================")
    log.info("CYCLE COMPLETE: %d VIDEOS PROCESSED", len(results))
    log.info("==================================================================")
    return results


def main():
    parser = argparse.ArgumentParser(description="VyralX Autonomous Production & Publishing Daemon")
    parser.add_argument("--interval-hours", type=float, default=6.0, help="Interval in hours between autonomous cycles")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--batch-size", type=int, default=2, help="Number of videos to produce per cycle")
    args = parser.parse_args()

    if args.once:
        run_autonomous_cycle(args.batch_size)
        return

    interval_sec = int(args.interval_hours * 3600)
    log.info("VyralX Daemon initialized. Running every %.1f hours (Press Ctrl+C to stop)...", args.interval_hours)
    while True:
        try:
            run_autonomous_cycle(args.batch_size)
        except Exception as e:
            log.exception("Error in autonomous cycle: %s", e)
        log.info("Sleeping for %.1f hours until next autonomous cycle...", args.interval_hours)
        time.sleep(interval_sec)


if __name__ == "__main__":
    main()
