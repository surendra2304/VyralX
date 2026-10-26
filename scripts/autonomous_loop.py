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

from app.services.autonomous_pipeline import (
    VideoJob,
    create_visual_job_from_source,
    run_pipeline,
)
from app.services.audience_reach_learner import (
    AudienceReachLearner,
    calculate_optimal_post_time,
    find_cohort_for_topic,
)

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [VyralX-AutoLoop] %(message)s"
)
log = logging.getLogger("vyralx.loop")

VERIFIED_VIRAL_CATALOG = [
    {"id": "31596", "title": "High Speed Supercar Drifting on Track", "topic": "hypercar extreme drift"},
    {"id": "47783", "title": "Hydraulic Press Crushing With Insane Pressure", "topic": "hydraulic press destruction"},
    {"id": "4075", "title": "Extreme Precision Domino Chain Reaction", "topic": "precision domino physics"},
    {"id": "29351", "title": "High Speed Wood Carving Lathe Spin", "topic": "satisfying woodturning craft"},
    {"id": "3780", "title": "Glass Blowing Molten Precision Artistry", "topic": "satisfying glass crafting"},
    {"id": "41576", "title": "Extreme Motorcycle Freestyle Track Stunts", "topic": "extreme motorsport stunts"},
    {"id": "5580", "title": "Molten Steel Glowing Pour in Industrial Foundry", "topic": "satisfying molten metal"},
    {"id": "5485", "title": "Precision Laser CNC Machine Cutting Metal", "topic": "satisfying precision cnc"},
    {"id": "14631", "title": "High Voltage Tesla Coil Electricity Dance", "topic": "high voltage tesla physics"},
]

SEARCH_TOPICS = [
    "extreme sports parkour visual stunts no commentary",
    "unbelievable physics trickshot extreme precision",
    "satisfying high speed supercar drift track visual",
    "hydraulic press crushing unexpected objects satisfying",
    "hypnotic domino falling chain reaction visual",
    "high voltage electric tesla coil lightning visual",
    "molten glass crafting blowing extreme precision"
]

DISQUALIFIED_KEYWORDS = {
    "podcast", "interview", "talking", "storytime", "mrbeast",
    "react", "reaction", "commentary", "vlog", "prank", "explained",
    "dialogue", "conversation", "speaking", "voiceover", "rant", "cheetah"
}


def is_clip_clean_and_silent(title: str, description: str) -> bool:
    """Rejects clips that already have commentary, spoken dialogue, or interview banter."""
    text_corpus = f"{title} {description}".lower()
    for kw in DISQUALIFIED_KEYWORDS:
        if kw in text_corpus:
            log.warning("Disqualifying candidate '%s': matched talking keyword '%s'", title[:40], kw)
            return False
    return True


def search_and_download_viral_clip(query: str, download_dir: Path) -> Path | None:
    """Uses yt-dlp to find and download a top-velocity vertical viral short with zero dialogue."""
    download_dir.mkdir(parents=True, exist_ok=True)
    log.info("Searching YouTube for clean visual candidate: '%s'...", query)

    search_cmd = [
        "yt-dlp",
        "--skip-download",
        "--dump-json",
        f"ytsearch8:{query}",
        "--match-filter", "duration <= 60 & duration >= 12"
    ]
    res = subprocess.run(search_cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if res.stdout:
        for line in res.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                d = json.loads(line)
                vid = d.get("id")
                title = d.get("title", "")
                desc = d.get("description", "")
                views = d.get("view_count", 0)
                dur = d.get("duration", 0)

                # Strict filter: Reject any clip with talking, commentary, or dialogue
                if not is_clip_clean_and_silent(title, desc):
                    continue

                # Look for clips with strong view velocity
                if views and views > 200_000:
                    dest_file = download_dir / f"{vid}.mp4"
                    if dest_file.exists():
                        log.info("Clip %s already exists on disk, reusing.", vid)
                        return dest_file

                    log.info("Found clean viral candidate: %s ('%s', %d views, %ds)", vid, title[:40], views, dur)
                    dl_cmd = [
                        "yt-dlp",
                        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                        "--merge-output-format", "mp4",
                        "-o", str(dest_file),
                        f"https://youtube.com/shorts/{vid}"
                    ]
                    dl_res = subprocess.run(dl_cmd, capture_output=True)
                    if dest_file.exists() and dest_file.stat().st_size > 0:
                        meta_file = download_dir / f"{vid}.json"
                        meta_file.write_text(
                            json.dumps({
                                "id": vid,
                                "title": title,
                                "views": views,
                                "duration": dur,
                                "description": desc
                            }, indent=2),
                            encoding="utf-8"
                        )
                        log.info("Successfully ingested clean source: %s (%.2f MB)", dest_file.name, dest_file.stat().st_size / (1024 * 1024))
                        return dest_file
            except Exception as e:
                continue

    # Fallback: Mixkit Licensed High-Motion Video Library (100% reliable on cloud datacenter IPs)
    log.info("Checking Mixkit high-motion CDN for candidate query: '%s'...", query)
    try:
        from app.services.mixkit import import_video_file, search_videos
        mix_results = search_videos(query, max_results=8)
        for item in mix_results:
            vid = str(item.get("id"))
            dest_file = download_dir / f"mixkit_{vid}.mp4"
            if dest_file.exists() and dest_file.stat().st_size > 100_000:
                log.info("Mixkit clip %s already exists on disk, reusing.", dest_file.name)
                return dest_file

            imported = import_video_file(
                video_id=vid,
                download_url=item.get("download_url", ""),
                fallback_url=item.get("fallback_url", ""),
                title=item.get("title", f"Visual Craft {vid}")
            )
            downloaded = Path(imported["file_path"])
            if downloaded.exists() and downloaded.stat().st_size > 100_000:
                import shutil
                shutil.copy2(downloaded, dest_file)
                meta_file = download_dir / f"mixkit_{vid}.json"
                meta_file.write_text(
                    json.dumps({
                        "id": f"mixkit_{vid}",
                        "title": item.get("title", query.title()),
                        "description": f"Satisfying high-speed visual demonstration: {query}",
                        "duration": 24,
                    }, indent=2),
                    encoding="utf-8"
                )
                log.info("Successfully ingested clean Mixkit source: %s (%.2f MB)", dest_file.name, dest_file.stat().st_size / (1024 * 1024))
                return dest_file
    except Exception as exc:
        log.warning("Mixkit candidate retrieval notice: %s", exc)

    return None


def get_processed_video_ids() -> set[str]:
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


def run_autonomous_cycle(batch_size: int = 1):
    """Executes a single end-to-end autonomous discovery, learning, production, and drafting cycle."""
    log.info("==================================================================")
    log.info("STARTING VYRALX 24/7 AUTONOMOUS CYCLE (BATCH SIZE: %d)", batch_size)
    log.info("==================================================================")

    # 1. Initialize Audience & Reach Learning Engine
    learner = AudienceReachLearner()
    manifest_path = Path("data/published_shorts_manifest.json")
    try:
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    except Exception:
        existing_manifest = []

    # 2. Refresh YouTube reach metrics and update topic reinforcement weights
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
    source_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[tuple[Path, str, dict[str, Any]]] = []

    # 3. Select fresh candidates using learned audience reach weights
    while len(candidates) < batch_size:
        chosen_entry, chosen_weight = learner.select_weighted_candidate(VERIFIED_VIRAL_CATALOG, processed_ids)
        if not chosen_entry:
            log.warning("All verified catalog candidates have been processed or none available.")
            break

        vid = str(chosen_entry["id"])
        cand_stem = f"mixkit_{vid}"
        dest_file = source_dir / f"{cand_stem}.mp4"

        if not dest_file.exists() or dest_file.stat().st_size < 100_000:
            log.info(
                "Ingesting candidate from CDN: %s ('%s', topic: '%s', weight: %.2f)...",
                cand_stem, chosen_entry["title"], chosen_entry["topic"], chosen_weight
            )
            try:
                import httpx
                url = f"https://assets.mixkit.co/videos/{vid}/{vid}-720.mp4"
                with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                    with client.stream("GET", url) as resp:
                        if resp.status_code == 200:
                            with open(dest_file, "wb") as f:
                                for chunk in resp.iter_bytes(chunk_size=65536):
                                    f.write(chunk)
            except Exception as dl_err:
                log.warning("Failed to download catalog clip %s: %s", vid, dl_err)
                processed_ids.add(cand_stem)
                continue

        if dest_file.exists() and dest_file.stat().st_size > 100_000:
            meta_file = source_dir / f"{cand_stem}.json"
            meta_file.write_text(
                json.dumps({
                    "id": cand_stem,
                    "title": chosen_entry["title"],
                    "description": f"Hypnotic high-retention visual action: {chosen_entry['topic']}",
                    "duration": 25,
                    "topic": chosen_entry["topic"],
                    "selection_weight": chosen_weight
                }, indent=2),
                encoding="utf-8"
            )
            # Calculate optimal posting time & target audience cohort
            schedule_info = calculate_optimal_post_time(chosen_entry["topic"])
            schedule_info["selection_weight"] = chosen_weight
            candidates.append((dest_file, chosen_entry["topic"], schedule_info))
            processed_ids.add(cand_stem)
            log.info(
                "Selected Candidate: %s ('%s') | Cohort: '%s' | Optimal Post Time: %s",
                dest_file.name, chosen_entry["title"],
                schedule_info["target_audience_cohort"],
                schedule_info["optimal_post_time_ist"]
            )

    # 4. Fallback search if catalog exhausted
    if len(candidates) < batch_size:
        for topic in SEARCH_TOPICS:
            clip = search_and_download_viral_clip(topic, source_dir)
            if clip and clip.stem not in processed_ids:
                sched = calculate_optimal_post_time(topic)
                candidates.append((clip, topic, sched))
                processed_ids.add(clip.stem)
                if len(candidates) >= batch_size:
                    break

    if not candidates:
        log.warning("No eligible viral candidates found in this cycle.")
        return []

    # 5. Perform frame-grounded Multimodal Vision Analysis for each candidate
    jobs: list[tuple[VideoJob, str, dict[str, Any]]] = []
    for c_path, topic, sched in candidates:
        try:
            job = create_visual_job_from_source(c_path, voice="en-US-GuyNeural")
            job.privacy_status = "private"  # STRICTLY DRAFT
            jobs.append((job, topic, sched))
        except Exception as e:
            log.exception("Vision analysis failed for %s: %s", c_path.name, e)

    if not jobs:
        log.error("Failed to generate visual jobs for any candidate.")
        return []

    # 6. Render and publish strictly to Drafts
    video_jobs_only = [j[0] for j in jobs]
    results = run_pipeline(video_jobs_only)

    # 7. Match results with learning metadata and update manifests
    for idx, r in enumerate(results):
        if idx < len(jobs):
            _, topic, sched = jobs[idx]
            r["topic"] = topic
            r["privacy"] = "private"
            r["status"] = "draft"
            r["audience_learning"] = {
                "target_audience_cohort": sched.get("target_audience_cohort"),
                "optimal_post_time_utc": sched.get("optimal_post_time_utc"),
                "optimal_post_time_ist": sched.get("optimal_post_time_ist"),
                "optimal_post_time_est": sched.get("optimal_post_time_est"),
                "posting_rationale": sched.get("posting_rationale"),
                "topic_weight": sched.get("selection_weight", 1.0)
            }
            uploaded_id = r.get("youtube_id") or r.get("yt_id")
            if uploaded_id:
                learner.record_draft_created(uploaded_id, topic, sched)

    # 8. Update published manifest
    try:
        existing = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    except Exception:
        existing = []

    for r in results:
        if r.get("status") in ("published", "draft", "staged_quota_limited"):
            existing.append(r)
    manifest_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    log.info("==================================================================")
    log.info("CYCLE COMPLETE: %d DRAFT SHORT(S) PRODUCED & SCHEDULED", len(results))
    for r in results:
        learn = r.get("audience_learning", {})
        log.info(
            "Draft: %s | Watch URL: %s | Optimal Post: %s (%s)",
            r.get("title", "Untitled"),
            r.get("watch_url"),
            learn.get("optimal_post_time_ist"),
            learn.get("target_audience_cohort")
        )
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
