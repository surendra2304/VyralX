"""VyralX 24/7 Autonomous Viral Shorts Loop Engine.

Autonomously runs the entire lifecycle on a scheduled cadence:
1. Selection: Selects un-produced authentic viral clips from MASTER_CATALOG using audience reach learning.
2. Voiceover Synthesis: Synthesizes high-hook narrative commentary using en-US-GuyNeural.
3. Typography: Renders Anton Bold at 96pt in the safe zone (MarginV=420) with electric cyan keyword highlights.
4. Audio Mastering: 20% original room audio ducked under voiceover + EBU R128 -14 LUFS loudnorm.
5. Video Composition: Full-bleed vertical 1080x1920 @ 60fps with contrast/saturation enhancements.
6. Audience Learning & Timing: Calculates optimal posting window per topic cohort.
7. Safe Drafting: Uploads strictly as private drafts (privacyStatus: private) to YouTube Studio for user review.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.audience_reach_learner import AudienceReachLearner, calculate_optimal_post_time
from scripts.render_master_candidate import MASTER_CATALOG, render_and_draft_video

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [VyralX-AutoLoop] %(message)s"
)
log = logging.getLogger("vyralx.loop")


def get_processed_video_ids() -> set[str]:
    """Retrieves all video IDs that have already been published or drafted."""
    ids = set()
    for p in [Path("data/published_shorts_manifest.json"), Path("data/autonomous_run_manifest.json")]:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                for item in data:
                    for key in ("video_id", "id", "yt_id", "youtube_id"):
                        val = item.get(key)
                        if val:
                            ids.add(str(val))
            except Exception:
                pass
    return ids


def run_autonomous_cycle(batch_size: int = 1) -> list[dict[str, Any]]:
    """Executes a single end-to-end master candidate discovery, rendering, and drafting cycle."""
    log.info("==================================================================")
    log.info("STARTING VYRALX MASTER AUTONOMOUS CYCLE (BATCH SIZE: %d)", batch_size)
    log.info("==================================================================")

    # 1. Initialize Audience & Reach Learning Engine
    learner = AudienceReachLearner()
    manifest_path = Path("data/published_shorts_manifest.json")
    try:
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    except Exception:
        existing_manifest = []

    # 2. Refresh channel reach metrics and update topic reinforcement weights
    log.info("Refreshing channel reach and learning from existing audience telemetry...")
    learning_summary = learner.refresh_and_learn(existing_manifest)
    log.info(
        "Audience Learning State: Completed %d cycles, %d drafts created. Active topic weights: %s",
        learning_summary.get("total_cycles", 1),
        learning_summary.get("total_drafts_created", 0),
        json.dumps(learning_summary.get("active_topic_weights", {}), indent=None)
    )

    processed_ids = get_processed_video_ids()
    source_dir = Path("media/viral_sources").resolve()

    # 3. Filter MASTER_CATALOG for un-produced candidates
    available_candidates: list[dict[str, Any]] = []
    for vid, conf in MASTER_CATALOG.items():
        if vid in processed_ids:
            continue
        vfile = source_dir / f"{vid}.mp4"
        if not vfile.exists():
            log.warning("Source file missing for candidate %s: %s", vid, vfile)
            continue
        available_candidates.append({
            "id": vid,
            "title": conf["title"],
            "topic": conf["topic"],
            "conf": conf
        })

    if not available_candidates:
        log.warning("All master viral candidates have been drafted! Waiting for next queue.")
        return []

    # 4. Select candidate using learned audience reach weights
    results: list[dict[str, Any]] = []
    for _ in range(min(batch_size, len(available_candidates))):
        chosen_entry, chosen_weight = learner.select_weighted_candidate(available_candidates, processed_ids)
        if not chosen_entry:
            break

        vid = str(chosen_entry["id"])
        conf = chosen_entry["conf"]

        log.info(
            "Selected Master Candidate: %s ('%s', topic: '%s', weight: %.2f)",
            vid, conf["title"], conf["topic"], chosen_weight
        )

        try:
            result = render_and_draft_video(vid, conf)
            results.append(result)
            processed_ids.add(vid)
            log.info("Successfully produced and drafted master short: %s -> %s", vid, result["watch_url"])
        except Exception as err:
            log.exception("Error rendering master candidate %s: %s", vid, err)

    return results


def run_continuous_daemon(interval_minutes: int = 180):
    """Runs continuous autonomous loop at specified intervals."""
    log.info("Starting VyralX continuous autonomous daemon (Interval: %d mins)...", interval_minutes)
    while True:
        try:
            run_autonomous_cycle(batch_size=1)
        except Exception as e:
            log.exception("Loop error during autonomous cycle: %s", e)
        log.info("Sleeping for %d minutes until next autonomous cycle...", interval_minutes)
        time.sleep(interval_minutes * 60)


def main():
    parser = argparse.ArgumentParser(description="VyralX Autonomous Loop Engine")
    parser.add_argument("--once", action="store_true", help="Run a single autonomous cycle and exit")
    parser.add_argument("--batch", type=int, default=1, help="Number of shorts to produce in cycle")
    parser.add_argument("--interval", type=int, default=180, help="Interval in minutes for continuous daemon")
    args = parser.parse_args()

    if args.once:
        run_autonomous_cycle(batch_size=args.batch)
    else:
        run_continuous_daemon(interval_minutes=args.interval)


if __name__ == "__main__":
    main()
