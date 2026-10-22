"""VyralX Algorithm Booster & Growth Optimization Engine.

Provides viral engagement catalysts, dual-screen retention video rendering,
cross-platform packaging, and optimal posting time calculations.
"""
from __future__ import annotations

import logging
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings

log = logging.getLogger("vyralx.booster")

ENGAGEMENT_CATALYSTS: dict[str, list[str]] = {
    "WILDLIFE": [
        "Would you pet a wild cheetah if you had the chance? YES or NO? 🐆👇",
        "On a scale of 1-10, how terrified would you be? 💀👇",
        "Tag a friend who would freeze up instantly 😂👇",
    ],
    "LIFEHACKS": [
        "Did you already know about this survival trick? Be honest! 🏕️👇",
        "Rate this life hack from 1 to 10! 🔥👇",
        "What is the single most useful hack you've ever learned? 👇",
    ],
    "COMEDY": [
        "Tag that ONE friend who always pulls this stunt 💀👇",
        "Was he wrong for doing that? Drop your verdict below! 😂👇",
        "Rate this reaction from 1 to 100! 👇",
    ],
    "SPORTS": [
        "Is this the greatest sportsmanship moment ever recorded? 🏆👇",
        "Real respect or just playing for the cameras? What's your take? 👇",
        "Who is your all-time favorite athlete? Comment below! ⚽🏀👇",
    ],
    "VIRAL": [
        "What would you do if this happened right in front of you? 😱👇",
        "Real or 100% staged? Let's settle the debate! 🎬👇",
        "Rate this moment: 10/10 or Overrated? 🔥👇",
    ],
}


def get_engagement_catalyst(category: str) -> str:
    """Return a high-conversion comment prompt designed to trigger debates."""
    cat = str(category).upper()
    pool = ENGAGEMENT_CATALYSTS.get(cat, ENGAGEMENT_CATALYSTS["VIRAL"])
    return random.choice(pool)


def compute_optimal_publish_time() -> dict[str, Any]:
    """Calculate the highest-concurrency posting windows for viral Shorts & Reels."""
    now_utc = datetime.now(timezone.utc)
    # Peak short-form consumption windows (US EST / Europe / Global overlap):
    # Window A: 12:00 - 15:00 UTC (Lunch rush Europe / morning US)
    # Window B: 18:00 - 22:00 UTC (Evening US / Late night Europe)
    current_hour = now_utc.hour

    if current_hour < 12:
        recommended = "13:30 UTC (8:30 AM EST / 6:00 PM IST)"
        reason = "Captures morning US commuters and European lunch rush"
    elif current_hour < 18:
        recommended = "19:00 UTC (2:00 PM EST / 11:30 PM IST)"
        reason = "Captures US afternoon peak and global evening entertainment cycle"
    else:
        recommended = "22:30 UTC (5:30 PM EST / next morning Asia)"
        reason = "Captures US prime evening leisure hours and early Asia commute"

    return {
        "current_utc_hour": current_hour,
        "recommended_window": recommended,
        "strategy": reason,
        "frequency_target": "3 to 5 Shorts daily for maximum algorithmic reach",
    }


def render_dual_screen_retention_short(
    main_video_path: Path,
    broll_video_path: Path,
    output_path: Path,
    hook_banner: str,
    bgm_path: Path | None = None,
    bgm_volume: float = 0.12,
    target_duration: float | None = None,
    category: str = "VIRAL",
) -> Path:
    """Render a high-retention split-screen Short with modern sleek divider and dynamic lower-third subtitle."""
    settings = get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    from app.services.video_styler import clean_for_drawtext, get_genre_profile
    profile = get_genre_profile(category)
    clean_hook = clean_for_drawtext(hook_banner)

    # Clean sleek divider (cyan/neon glow) and frosted pill subtitle
    font_file = f"C\\:/Windows/Fonts/{profile.font_name}"
    subtitle_filter = (
        f"drawtext=fontfile='{font_file}':"
        f"text='{clean_hook}':"
        f"fontsize={profile.font_size}:"
        f"fontcolor={profile.primary_color}:"
        f"borderw=3:bordercolor={profile.outline_color}:"
        f"box=1:boxcolor={profile.box_color}:boxborderw=10:"
        f"x=(w-text_w)/2:y=910"  # Placed right above the sleek center divider
    )

    filter_complex = (
        "[0:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,eq=contrast=1.06:saturation=1.12[top_v];"
        "[1:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,eq=contrast=1.05:saturation=1.10[bot_v];"
        "[top_v][bot_v]vstack=inputs=2,"
        "drawbox=x=0:y=958:w=1080:h=4:color=0x00E5FF@0.9:t=fill,"  # Sleek Cyber Cyan divider
        f"{subtitle_filter}[outv]"
    )

    inputs = [
        "-i", str(main_video_path),
        "-stream_loop", "-1", "-i", str(broll_video_path),
    ]

    if bgm_path and bgm_path.is_file():
        inputs.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
        audio_filter = (
            f"[2:a]volume={bgm_volume:.2f}[bgm];"
            "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0,loudnorm=I=-14:LRA=9:TP=-1.5[outa]"
        )
        filter_complex += f";{audio_filter}"
        map_args = ["-map", "[outv]", "-map", "[outa]"]
    else:
        map_args = ["-map", "[outv]", "-map", "0:a?"]

    dur = target_duration
    if not dur:
        try:
            probe_cmd = [
                settings.ffprobe_bin, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(main_video_path),
            ]
            res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
            dur = float(res.stdout.strip())
        except Exception:
            dur = 35.0

    cmd = [
        settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        *map_args,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-t", str(float(dur)),
        "-movflags", "+faststart",
        str(output_path),
    ]

    log.info("Rendering dual-screen retention Short to %s...", output_path)
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path
