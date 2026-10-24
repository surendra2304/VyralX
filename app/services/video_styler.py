"""VyralX Adaptive Video & Subtitle Styler.

Provides genre-adapted, non-intrusive subtitle typography, timed visual pacing,
and cinematic styling tailored to each specific video category.
Eliminates static yellow banners and replaces them with sleek, dynamic, well-positioned subtitles.
"""
from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings

log = logging.getLogger("vyralx.video_styler")


def clean_for_drawtext(text: str) -> str:
    """Clean text for FFmpeg drawtext: strip emojis and escape colons/quotes."""
    # Strip non-ASCII (emojis) so Windows fonts don't render missing-glyph square boxes
    ascii_only = re.sub(r"[^\x00-\x7F]+", "", text)
    # Remove quotes, semicolons, brackets, backslashes, percent signs
    sanitized = ascii_only.replace("'", "").replace('"', "").replace(":", r"\:").replace(",", "").replace("%", "")
    return sanitized.strip()


@dataclass(frozen=True)
class GenreStyleProfile:
    genre: str
    font_name: str
    primary_color: str
    accent_color: str
    outline_color: str
    box_color: str
    font_size: int
    y_position: int  # Lower-third sweet spot (typically 1380 to 1480 for 1080x1920)
    badge_color: tuple[int, int, int]
    badge_label: str


GENRE_PROFILES: dict[str, GenreStyleProfile] = {
    "WILDLIFE": GenreStyleProfile(
        genre="WILDLIFE",
        font_name="arialbd.ttf",
        primary_color="white",
        accent_color="0x00E5FF",  # Electric Cyan
        outline_color="black",
        box_color="black@0.45",
        font_size=46,
        y_position=1420,
        badge_color=(0, 229, 255),
        badge_label="WILDLIFE",
    ),
    "LIFEHACKS": GenreStyleProfile(
        genre="LIFEHACKS",
        font_name="arialbd.ttf",
        primary_color="white",
        accent_color="0x00FF88",  # Neon Emerald
        outline_color="black",
        box_color="black@0.45",
        font_size=46,
        y_position=1420,
        badge_color=(0, 255, 136),
        badge_label="LIFE HACK",
    ),
    "COMEDY": GenreStyleProfile(
        genre="COMEDY",
        font_name="impact.ttf",
        primary_color="white",
        accent_color="0xFFDF00",  # Bright Pop Yellow
        outline_color="black",
        box_color="black@0.40",
        font_size=52,
        y_position=1400,
        badge_color=(255, 223, 0),
        badge_label="COMEDY",
    ),
    "SPORTS": GenreStyleProfile(
        genre="SPORTS",
        font_name="impact.ttf",
        primary_color="white",
        accent_color="0xFFD700",  # Championship Gold
        outline_color="black",
        box_color="black@0.45",
        font_size=50,
        y_position=1420,
        badge_color=(255, 215, 0),
        badge_label="RESPECT",
    ),
    "VIRAL": GenreStyleProfile(
        genre="VIRAL",
        font_name="impact.ttf",
        primary_color="white",
        accent_color="0x00F0FF",  # Cyber Neon Blue
        outline_color="black",
        box_color="black@0.45",
        font_size=52,
        y_position=1410,
        badge_color=(0, 240, 255),
        badge_label="VIRAL",
    ),
}

# Timed dynamic subtitle beats per category (Hook for first 3.8s, Context cue for mid-video)
GENRE_SUBTITLE_BEATS: dict[str, list[dict[str, Any]]] = {
    "WILDLIFE": [
        {"start": 0.0, "end": 3.8, "text": "DO NOT RUN"},
        {"start": 4.0, "end": 10.0, "text": "Listen to that purr..."},
        {"start": 10.5, "end": 20.0, "text": "He did not flinch once"},
        {"start": 20.5, "end": 38.0, "text": "Nature is truly unreal"},
    ],
    "LIFEHACKS": [
        {"start": 0.0, "end": 3.8, "text": "GENIUS SURVIVAL HACK"},
        {"start": 4.0, "end": 10.0, "text": "This trick saves lives"},
        {"start": 10.5, "end": 20.0, "text": "Notice how simple this is"},
        {"start": 20.5, "end": 34.0, "text": "Save this for your next trip"},
    ],
    "COMEDY": [
        {"start": 0.0, "end": 3.5, "text": "BRO DID NOT HESITATE"},
        {"start": 3.8, "end": 8.5, "text": "That one friend we all have"},
        {"start": 9.0, "end": 16.0, "text": "Wait for his reaction"},
    ],
    "SPORTS": [
        {"start": 0.0, "end": 3.8, "text": "PURE RESPECT IN SPORTS"},
        {"start": 4.0, "end": 10.0, "text": "Bigger than winning"},
        {"start": 10.5, "end": 22.0, "text": "A true champions heart"},
    ],
    "VIRAL": [
        {"start": 0.0, "end": 3.8, "text": "WAIT FOR THE END"},
        {"start": 4.0, "end": 11.0, "text": "Nobody saw this coming"},
        {"start": 11.5, "end": 24.0, "text": "Watch this twice"},
    ],
}


def get_genre_profile(category: str) -> GenreStyleProfile:
    cat_key = str(category).upper()
    return GENRE_PROFILES.get(cat_key, GENRE_PROFILES["VIRAL"])


def build_dynamic_subtitle_filter(category: str, custom_hook: str | None = None) -> str:
    """Build FFmpeg drawtext filter chains with timed enable windows and lower-third placement.
    
    Eliminates fixed yellow top banners. Places clean, frosted-pill subtitles in the lower-third,
    timed to animate in and out at key pacing moments.
    """
    cat_key = str(category).upper()
    profile = get_genre_profile(cat_key)
    beats = list(GENRE_SUBTITLE_BEATS.get(cat_key, GENRE_SUBTITLE_BEATS["VIRAL"]))

    if custom_hook:
        beats[0] = {"start": 0.0, "end": 3.8, "text": custom_hook}

    filters = []
    # Windows font file path formatted safely for FFmpeg filter_complex
    font_file = f"C\\:/Windows/Fonts/{profile.font_name}"

    for beat in beats:
        clean_text = clean_for_drawtext(beat["text"])
        if not clean_text:
            continue
        start_t = beat["start"]
        end_t = beat["end"]
        # Sleek lower-third subtitle with semi-transparent rounded pill box and crisp stroke
        filter_item = (
            f"drawtext=fontfile='{font_file}':"
            f"text='{clean_text}':"
            f"fontsize={profile.font_size}:"
            f"fontcolor={profile.primary_color}:"
            f"borderw=3:bordercolor={profile.outline_color}:"
            f"box=1:boxcolor={profile.box_color}:boxborderw=10:"
            f"x=(w-text_w)/2:y={profile.y_position}:"
            f"enable='between(t\\,{start_t}\\,{end_t})'"
        )
        filters.append(filter_item)

    return ",".join(filters)


def render_adaptive_short(
    source_video_path: Path,
    output_path: Path,
    category: str,
    custom_hook: str | None = None,
    bgm_path: Path | None = None,
    bgm_volume: float = 0.12,
    target_duration: float | None = None,
) -> Path:
    """Render a full-bleed vertical 1080x1920 Short with genre-adapted dynamic subtitles and subtle BGM."""
    settings = get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    subtitle_filters = build_dynamic_subtitle_filter(category, custom_hook)

    # Clean vertical scaling with high visual pop: contrast 1.05, saturation 1.10
    video_filter = (
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,eq=contrast=1.05:saturation=1.10,"
        f"{subtitle_filters}[v]"
    )

    cmd = [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i", str(source_video_path),
    ]

    has_bgm = bgm_path is not None and bgm_path.is_file()
    if has_bgm:
        cmd.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
        # Original audio at 100% volume, subtle rotating BGM at 12-14% volume
        filter_complex = (
            f"{video_filter};"
            f"[0:a]volume=1.0[orig_a];"
            f"[1:a]volume={bgm_volume}[bgm_a];"
            f"[orig_a][bgm_a]amix=inputs=2:duration=first:dropout_transition=2[a]"
        )
    else:
        filter_complex = f"{video_filter};[0:a]volume=1.0[a]"

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "faster",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
    ])

    if target_duration:
        cmd.extend(["-t", str(target_duration)])

    cmd.append(str(output_path))

    log.info("Rendering adaptive short for %s: %s", category, output_path.name)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        log.error("Adaptive render failed: %s", proc.stderr[-800:])
        raise RuntimeError(f"FFmpeg adaptive render failed: {proc.stderr[-400:]}")

    log.info("Adaptive render complete: %s (%.2f MB)", output_path.name, output_path.stat().st_size / (1024 * 1024))
    return output_path
