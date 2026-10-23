"""VyralX Premium Commentary Re-editor for User's Top 2 Chosen Formats.

Videos:
1. A_Q2qpbHrqo (9,999,999$ Deal)
2. hx265ujsLVU (Pure Chaos)

Features:
- Fixed voice: en-US-GuyNeural
- Rapid 2-3 word synchronized bursts
- 100% screen-safe ASS subtitles (Segoe UI Bold, 44pt, razor-sharp outline, subtle drop shadow, gold keyword accents)
- YouTube Shorts UI Safe Zone (MarginV: 380) - zero text cutoff, zero clipping
- Balanced audio ducking (commentary 100%, background 20%, loudnorm broadcast mastering)
- Output directly to: d:/FRIDAY Universe/VyralX/media/edited_videos/
"""
from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import edge_tts

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vyralx.reedit_favorites")

TARGET_VIDEOS = {
    "A_Q2qpbHrqo": {
        "title": "The 9,999,999 Dollar Negotiation Meme",
        "category": "VIRAL",
        "voice": "en-US-GuyNeural",
        "script": (
            "When this customer jokingly asked for a discount, the salesman hit him with the ultimate counter-offer: "
            "nine million, nine hundred ninety-nine thousand dollars. "
            "The stone-cold deadpan delivery turned an everyday interaction into one of the most viral negotiation memes on the internet."
        ),
        "highlight_words": {"DISCOUNT", "SALESMAN", "ULTIMATE", "COUNTER-OFFER", "NINE", "MILLION", "NINE-HUNDRED", "NINETY-NINE", "THOUSAND", "DOLLARS", "STONE-COLD", "DEADPAN", "VIRAL", "MEMES", "INTERNET", "9,999,999$"},
    },
    "hx265ujsLVU": {
        "title": "Pure Chaos Caught on Camera",
        "category": "VIRAL",
        "voice": "en-US-GuyNeural",
        "script": (
            "From zero to complete chaos in under four seconds. "
            "This is the kind of once-in-a-lifetime chain reaction that nobody would ever believe if it wasn't caught on camera."
        ),
        "highlight_words": {"ZERO", "COMPLETE", "CHAOS", "FOUR", "SECONDS", "ONCE-IN-A-LIFETIME", "CHAIN", "REACTION", "NOBODY", "BELIEVE", "CAMERA"},
    },
}

def sec_to_ass(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:d}:{m:02d}:{sec:05.2f}"

async def synthesize_voice_and_cues(script: str, voice: str, out_audio: Path) -> list[dict[str, Any]]:
    comm = edge_tts.Communicate(script, voice)
    audio_data = b""
    cues: list[dict[str, Any]] = []

    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
        elif chunk["type"] == "SentenceBoundary":
            st = chunk["offset"] / 1e7
            dur = chunk["duration"] / 1e7
            sentence = chunk["text"].strip()
            words = sentence.split()
            if not words:
                continue

            # Group into punchy 2-3 word chunks for high-retention Shorts pacing
            chunk_size = 2 if len(words) <= 5 else 3
            chunks = [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]
            total_chars = sum(len(c) for c in chunks)
            curr = st
            for ch in chunks:
                ch_dur = dur * (len(ch) / total_chars)
                cues.append({"start": curr, "end": curr + ch_dur, "text": ch})
                curr += ch_dur

    out_audio.parent.mkdir(parents=True, exist_ok=True)
    out_audio.write_bytes(audio_data)
    log.info("Synthesized voiceover: %s (%.1fs)", out_audio.name, cues[-1]["end"] if cues else 0)
    return cues

def generate_attractive_ass(cues: list[dict[str, Any]], highlights: set[str], ass_path: Path):
    """Generate high-end aesthetic ASS subtitle styling:
    - Font: Segoe UI Bold / Impact style
    - Size: 44 (perfect readable mobile scale, zero overflow)
    - Colors: Pure white text with radiant gold accents on key impact words
    - Stroke: Razor-sharp 3.5px black outline + 2.0px soft ambient drop shadow
    - Safe margins: MarginL=100, MarginR=100, MarginV=380 (no UI collisions, no cutoffs)
    """
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: AttractiveShorts,Segoe UI,44,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,3.5,2.0,2,100,100,380,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    gold_color = r"{\c&H0024E8FF&}" # ASS color is &HAABBGGRR -> Yellow-Gold: BB=24, GG=E8, RR=FF
    white_color = r"{\c&H00FFFFFF&}"

    for cue in cues:
        st = sec_to_ass(cue["start"])
        et = sec_to_ass(cue["end"])
        raw_words = cue["text"].upper().split()
        styled_words = []
        for w in raw_words:
            clean_w = re.sub(r"[^A-Z0-9$]", "", w)
            if clean_w in highlights or any(char.isdigit() for char in clean_w) or "$" in clean_w:
                styled_words.append(f"{gold_color}{w}{white_color}")
            else:
                styled_words.append(w)
        line_text = " ".join(styled_words)
        events.append(f"Dialogue: 0,{st},{et},AttractiveShorts,,0,0,0,,{line_text}")

    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text(header + "\n".join(events), encoding="utf-8")
    log.info("Generated aesthetic ASS subtitle script: %s (%d events)", ass_path.name, len(events))

def render_short(vid: str, info: dict[str, Any]):
    source = Path(f"media/viral_sources/{vid}.mp4")
    out_dir = Path("media/edited_videos")
    out_dir.mkdir(parents=True, exist_ok=True)

    dest_video = out_dir / f"vyralx-commentary-{vid}.mp4"
    audio_path = Path(f"media/voiceovers/guy_{vid}.mp3")
    ass_path = Path(f"media/voiceovers/subs_{vid}.ass")

    # 1. Synthesize audio & cues
    cues = asyncio.run(synthesize_voice_and_cues(info["script"], info["voice"], audio_path))

    # 2. Build attractive ASS subtitles
    generate_attractive_ass(cues, info["highlight_words"], ass_path)

    # 3. Render video via FFmpeg with libass subtitles and ducked audio
    # Escape path for ffmpeg subtitles filter (replace backslashes with forward slashes)
    ass_filter_path = str(ass_path).replace("\\", "/")
    if ":" in ass_filter_path:
        # e.g., D:/FRIDAY -> D\\:/FRIDAY
        drive, rest = ass_filter_path.split(":", 1)
        ass_filter_path = f"{drive}\\:{rest}"

    video_filter = (
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,eq=contrast=1.06:saturation=1.12,"
        f"subtitles='{ass_filter_path}'[v]"
    )

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
        "-i", str(source),
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

    log.info("Rendering %s -> %s...", vid, dest_video)
    subprocess.run(cmd, check=True)
    log.info("Render finished: %s (%.2f MB)", dest_video.name, dest_video.stat().st_size / (1024 * 1024))

    # Extract a representative preview frame at 3.5s to verify subtitles
    preview_frame = out_dir / f"preview_subtitle_{vid}.jpg"
    preview_cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-ss", "00:00:03.5",
        "-i", str(dest_video),
        "-vframes", "1",
        str(preview_frame),
    ]
    subprocess.run(preview_cmd, capture_output=True)
    log.info("Generated subtitle preview frame: %s", preview_frame.name)

def main():
    log.info("=== RE-EDITING USER'S 2 PREFERRED VIDEOS ===")
    for vid, info in TARGET_VIDEOS.items():
        render_short(vid, info)
    log.info("=== BOTH VIDEOS SUCCESSFULLY RE-EDITED ===")

if __name__ == "__main__":
    main()
