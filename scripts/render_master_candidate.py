#!/usr/bin/env python3
"""VyralX Master Benchmark Production Script.

Renders and drafts authentic viral shorts matching the exact quality of Videos 1 & 2:
- Genuine viral vertical video clip with real audio
- en-US-GuyNeural voiceover narration
- Anton Bold 96pt subtitles in the safe zone (MarginV=420)
- Dual-layer audio: original audio ducked to 20% + loudnorm -14 LUFS
- Strict private draft upload to YouTube Studio
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import edge_tts

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.services.audience_reach_learner import calculate_optimal_post_time
from app.services.youtube import upload_video

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [VyralX-Master] %(message)s")
log = logging.getLogger("vyralx.master")

MASTER_CATALOG = {
    "heI4DLab-l8": {
        "title": "Trying Not to Laugh in a Dead-Silent Classroom 😭💀 #Shorts",
        "topic": "school relatable comedy",
        "category_id": "24",
        "voice": "en-US-GuyNeural",
        "script": (
            "Nothing tests your poker face quite like trying not to burst out laughing in a dead-silent classroom. "
            "The exact second you make eye contact across the room, it is completely game over."
        ),
        "cyan_keywords": {"POKER", "FACE", "LAUGHING", "DEAD-SILENT", "CLASSROOM", "EYE", "CONTACT", "GAME", "OVER"},
        "debate_question": "What is the worst moment you ever burst out laughing? Drop it below! 😭👇",
        "tags": ["shorts", "comedy", "school humor", "relatable", "funny", "every student ever", "viral"]
    },
    "BmW5Qb3fqlk": {
        "title": "That One Golibaaz Friend We All Have 💀😂 | Pure Comedy #Shorts",
        "topic": "viral friendship comedy",
        "category_id": "24",
        "voice": "en-US-GuyNeural",
        "script": (
            "We all have that one friend whose stories get ten times more insane every single time he tells them. "
            "Watch the sheer disbelief on everyone's faces as his fictional story completely falls apart."
        ),
        "cyan_keywords": {"ONE", "FRIEND", "STORIES", "INSANE", "EVERY", "SINGLE", "TIME", "DISBELIEF", "FICTIONAL", "STORY", "FALLS", "APART"},
        "debate_question": "Tag that ONE friend who tells the craziest fake stories 😭👇",
        "tags": ["shorts", "comedy", "funny", "that one friend", "relatable", "friends", "viral comedy"]
    },
    "mHE8rDhCWAw": {
        "title": "Pure Respect and Sportsmanship That Melted Hearts 🤝❤️ #Shorts",
        "topic": "sportsmanship and respect",
        "category_id": "17",
        "voice": "en-US-GuyNeural",
        "script": (
            "When an opponent went down clutching his knee, this player immediately stopped an open-goal counterattack to call for medical help. "
            "Some moments are much bigger than trophies. This is what true respect in sports looks like."
        ),
        "cyan_keywords": {"OPPONENT", "CLUTCHING", "KNEE", "STOPPED", "OPEN-GOAL", "MEDICAL", "HELP", "BIGGER", "TROPHIES", "TRUE", "RESPECT", "SPORTS"},
        "debate_question": "Is this the greatest sportsmanship moment ever recorded? 🏆👇",
        "tags": ["shorts", "sports", "respect", "sportsmanship", "fair play", "football", "viral"]
    },
    "sOZrJUkCLYU": {
        "title": "Wait For The Most Unexpected Plot Twist 😱🤯 #Shorts",
        "topic": "shocking unexpected twists",
        "category_id": "24",
        "voice": "en-US-GuyNeural",
        "script": (
            "Watch closely right here. Everyone expected a standard outcome, but what unfolded in the next three seconds "
            "caught millions of viewers completely off guard."
        ),
        "cyan_keywords": {"WATCH", "CLOSELY", "EXPECTED", "OUTCOME", "UNFOLDED", "THREE", "SECONDS", "MILLIONS", "OFF", "GUARD"},
        "debate_question": "Did you see that plot twist coming? Be honest! 🤯👇",
        "tags": ["shorts", "viral", "plot twist", "unexpected", "wait for it", "trending"]
    },
    "8kggT2ej-lo": {
        "title": "Why Cheetahs Sound Like Sports Cars 🐆💨 | Nature Is Unreal #Shorts",
        "topic": "mind-blowing wildlife",
        "category_id": "24",
        "voice": "en-US-GuyNeural",
        "script": (
            "This might sound like a high-performance sports car, but it's actually an 8-month-old cheetah cub purring. "
            "Unlike lions and tigers, cheetahs cannot roar because they have a flexible vocal bone. "
            "Instead, they purr at a steady twenty-five Hertz whenever they feel completely safe and relaxed."
        ),
        "cyan_keywords": {"SPORTS", "CAR", "CHEETAH", "PURRING", "ROAR", "VOCAL", "BONE", "TWENTY-FIVE", "HERTZ", "SAFE", "RELAXED"},
        "debate_question": "Would you pet a wild cheetah if you had the chance? YES or NO? 🐆👇",
        "tags": ["shorts", "wildlife", "cheetah", "animals", "nature", "purring", "viral"]
    }
}


def sec_to_ass(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:d}:{m:02d}:{sec:05.2f}"


async def generate_speech_cues(text: str, voice: str, audio_file: Path) -> list[dict[str, Any]]:
    comm = edge_tts.Communicate(text, voice)
    audio_bytes = b""
    cues = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio_bytes += chunk["data"]
        elif chunk["type"] == "SentenceBoundary":
            st = chunk["offset"] / 1e7
            dur = chunk["duration"] / 1e7
            words = chunk["text"].strip().split()
            if not words:
                continue
            chunk_size = 2
            chunks = [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]
            total_chars = sum(len(c) for c in chunks)
            curr = st
            for ch in chunks:
                ch_dur = dur * (len(ch) / max(1, total_chars))
                cues.append({"start": curr, "end": curr + ch_dur, "text": ch})
                curr += ch_dur

    audio_file.parent.mkdir(parents=True, exist_ok=True)
    audio_file.write_bytes(audio_bytes)
    return cues


def create_anton_ass(cues: list[dict[str, Any]], cyan_words: set[str], ass_path: Path):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: AntonBold,Anton,96,&H00FFFFFF,&H000000FF,&H00000000,&HAA000000,0,0,0,0,100,100,1.5,0,1,6.0,3.5,2,70,70,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    cyan_code = r"{\c&H00FFE500&}"
    white_code = r"{\c&H00FFFFFF&}"

    clean_cyan = {re.sub(r"[^A-Z0-9]", "", w.upper()) for w in cyan_words}

    for c in cues:
        st = sec_to_ass(c["start"])
        et = sec_to_ass(c["end"])
        raw_words = c["text"].upper().split()
        styled = []
        for w in raw_words:
            clean_w = re.sub(r"[^A-Z0-9]", "", w)
            if clean_w in clean_cyan:
                styled.append(f"{cyan_code}{w}{white_code}")
            else:
                styled.append(w)
        line = " ".join(styled)
        events.append(f"Dialogue: 0,{st},{et},AntonBold,,0,0,0,,{line}")

    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text(header + "\n".join(events), encoding="utf-8")


def render_and_draft_video(vid: str, conf: dict[str, Any]) -> dict[str, Any]:
    source_file = Path(f"media/viral_sources/{vid}.mp4").resolve()
    if not source_file.exists():
        raise FileNotFoundError(f"Source file not found: {source_file}")

    dest_video = Path(f"media/edited_videos/vyralx-commentary-{vid}.mp4").resolve()
    audio_path = Path(f"media/voiceovers/voice_master_{vid}.mp3").resolve()
    ass_path = Path(f"media/voiceovers/subs_master_{vid}.ass").resolve()

    log.info("Processing viral masterpiece: %s ('%s')...", vid, conf["title"])

    # 1. Synthesize audio with en-US-GuyNeural
    cues = asyncio.run(generate_speech_cues(conf["script"], conf["voice"], audio_path))
    log.info("Voice synthesized: %s (%d cues)", audio_path.name, len(cues))

    # 2. Generate Anton Bold subtitles
    create_anton_ass(cues, conf["cyan_keywords"], ass_path)
    log.info("Subtitles built: %s (Anton Bold 96pt in safe zone)", ass_path.name)

    # 3. Path escaping for libass
    fonts_dir = str(Path("data/fonts").resolve()).replace("\\", "/")
    fonts_dir_escaped = f"{fonts_dir.split(':', 1)[0]}\\:{fonts_dir.split(':', 1)[1]}" if ":" in fonts_dir else fonts_dir
    ass_filter = str(ass_path).replace("\\", "/")
    ass_filter_escaped = f"{ass_filter.split(':', 1)[0]}\\:{ass_filter.split(':', 1)[1]}" if ":" in ass_filter else ass_filter

    # 4. Filter complex: 1080x1920 scale + crop + contrast boost + Anton subtitles
    video_filter = (
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,eq=contrast=1.06:saturation=1.12,"
        f"subtitles='{ass_filter_escaped}':fontsdir='{fonts_dir_escaped}'[v]"
    )

    # 5. Dual-Layer Audio Mix: 20% original room audio + 100% voiceover at -14 LUFS loudnorm
    audio_filter = (
        "[0:a]volume=0.20[orig_a];"
        "[1:a]volume=1.0[voice_a];"
        "[orig_a][voice_a]amix=inputs=2:duration=first:dropout_transition=2,loudnorm=I=-14:LRA=9:TP=-1.5[a]"
    )

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i", str(source_file),
        "-i", str(audio_path),
        "-filter_complex", f"{video_filter};{audio_filter}",
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "faster",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(dest_video),
    ]

    log.info("Rendering %s -> %s...", source_file.name, dest_video.name)
    subprocess.run(cmd, check=True)
    size_mb = dest_video.stat().st_size / (1024 * 1024)
    log.info("Render complete: %s (%.2f MB)", dest_video.name, size_mb)

    # 6. Upload strictly to DRAFTS (private)
    description = (
        f"{conf['script']}\n\n"
        f"💬 QUESTION OF THE DAY: {conf['debate_question']}\n\n"
        f"🔔 SUBSCRIBE to @VyralXAgent for daily unhinged comedy & viral moments!\n\n"
        f"#Shorts #Comedy #Viral #Trending #Relatable #VyralX"
    )

    log.info("Uploading %s to DRAFTS (privacy: private)...", conf["title"])
    yt_id = upload_video(
        file_path=str(dest_video),
        title=conf["title"],
        description=description,
        tags=conf["tags"],
        privacy_status="private",
        category_id=conf["category_id"]
    )
    watch_url = f"https://youtube.com/shorts/{yt_id}"
    log.info("DRAFT SAVED TO YOUTUBE STUDIO! Watch URL: %s", watch_url)

    # Calculate optimal post time
    sched = calculate_optimal_post_time(conf["topic"])

    # Update published manifest
    manifest_path = Path("data/published_shorts_manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    except Exception:
        manifest = []

    manifest.append({
        "video_id": vid,
        "yt_id": yt_id,
        "title": conf["title"],
        "watch_url": watch_url,
        "privacy": "private",
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "draft",
        "audience_learning": sched
    })
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "video_id": vid,
        "yt_id": yt_id,
        "title": conf["title"],
        "watch_url": watch_url,
        "status": "draft",
        "optimal_post_time": sched.get("optimal_post_time_ist")
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Render & Draft Master Viral Short")
    parser.add_argument("--video", type=str, default="heI4DLab-l8", help="Video ID to produce")
    args = parser.parse_args()

    vid = args.video
    if vid not in MASTER_CATALOG:
        log.error("Video ID %s not found in master catalog. Available: %s", vid, list(MASTER_CATALOG.keys()))
        sys.exit(1)

    result = render_and_draft_video(vid, MASTER_CATALOG[vid])
    log.info("==================================================================")
    log.info("MASTER DRAFT PRODUCED & SCHEDULED")
    log.info("Title: %s", result["title"])
    log.info("Draft URL: %s", result["watch_url"])
    log.info("Optimal Post: %s", result["optimal_post_time"])
    log.info("==================================================================")


if __name__ == "__main__":
    main()
