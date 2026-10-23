"""VyralX Ultra-Visible Anton Bold Shorts Generator.

Upgrades:
1. FONT: Switched from boring Arial to 'Anton' (the gold-standard viral YouTube Shorts font).
2. SIZE: Sized up to a massive 96pt (bold, clearly visible, impossible to miss on mobile).
3. PACING: 2-word bursts for punchy, rapid-fire reading.
4. STYLING: Thick 6.0px black stroke, 3.5px drop shadow, pure white text with electric cyan keyword pop.
5. NO 'SIR' in the commentary audio.
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
log = logging.getLogger("vyralx.anton_bold")

VIDEOS_CONFIG = {
    "A_Q2qpbHrqo": {
        "title": "When a 5-Star Michelin Restaurant Serves Soap Bubbles",
        "voice": "en-US-GuyNeural",
        "script": (
            "He dressed up in a luxury tuxedo for a five-star Michelin dinner, but the menu had other plans. "
            "Instead of gourmet food, the waitress serves him a plate of literal soap bubbles. "
            "And just when he thinks it cannot get any more ridiculous, she brings out a toy bubble gun and blasts his head with foam. "
            "The final bill for this soap dinner? Exactly nine million, nine hundred ninety-nine thousand dollars."
        ),
        "cyan_keywords": {
            "LUXURY", "TUXEDO", "MICHELIN", "DINNER", "GOURMET", "SOAP", "BUBBLES",
            "BUBBLE", "GUN", "BLASTS", "FOAM", "BILL", "NINE", "MILLION", "DOLLARS"
        },
    },
    "hx265ujsLVU": {
        "title": "When You Have Maximum Main Character Energy in the Hallway",
        "voice": "en-US-GuyNeural",
        "script": (
            "When your friends try to roast you in the hallway, but you have maximum main character energy. "
            "While the rest of the squad is laughing and joking around, she delivers the cleanest eye-roll on the internet "
            "and struts away without breaking character for a single second. That is how you own the room."
        ),
        "cyan_keywords": {
            "ROAST", "HALLWAY", "MAXIMUM", "MAIN", "CHARACTER", "ENERGY",
            "SQUAD", "CLEANEST", "EYE-ROLL", "INTERNET", "STRUTS", "OWN", "ROOM"
        },
    },
}

def sec_to_ass(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:d}:{m:02d}:{sec:05.2f}"

async def generate_speech(script: str, voice: str, audio_file: Path) -> list[dict[str, Any]]:
    comm = edge_tts.Communicate(script, voice)
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

            # Strict 2 words per cue (or 3 if very short) for big 96pt impact
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
    log.info("Audio saved: %s (%.1fs)", audio_file.name, cues[-1]["end"] if cues else 0)
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
Style: AntonBold,Anton,96,&H00FFFFFF,&H000000FF,&H00000000,&HAA000000,0,0,0,0,100,100,1.5,0,1,6.0,3.5,2,70,70,450,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    cyan_code = r"{\c&H00FFE500&}"
    white_code = r"{\c&H00FFFFFF&}"

    for c in cues:
        st = sec_to_ass(c["start"])
        et = sec_to_ass(c["end"])
        raw_words = c["text"].upper().split()
        styled = []
        for w in raw_words:
            clean = re.sub(r"[^A-Z0-9$]", "", w)
            if clean in cyan_words or any(char.isdigit() for char in clean) or "$" in clean:
                styled.append(f"{cyan_code}{w}{white_code}")
            else:
                styled.append(w)
        line = " ".join(styled)
        events.append(f"Dialogue: 0,{st},{et},AntonBold,,0,0,0,,{line}")

    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text(header + "\n".join(events), encoding="utf-8")
    log.info("Anton ASS created: %s (%d events)", ass_path.name, len(events))

def render_video(vid: str, conf: dict[str, Any]):
    source = Path(f"media/viral_sources/{vid}.mp4")
    out_dir = Path("media/edited_videos")
    dest_video = out_dir / f"vyralx-commentary-{vid}.mp4"

    audio_path = Path(f"media/voiceovers/guy_anton_{vid}.mp3")
    ass_path = Path(f"media/voiceovers/subs_anton_{vid}.ass")

    # 1. Synthesize audio
    cues = asyncio.run(generate_speech(conf["script"], conf["voice"], audio_path))

    # 2. Build Anton ASS
    create_anton_ass(cues, conf["cyan_keywords"], ass_path)

    # 3. Path escaping for libass & fontsdir
    fonts_dir = str(Path("data/fonts").resolve()).replace("\\", "/")
    if ":" in fonts_dir:
        drive, rest = fonts_dir.split(":", 1)
        fonts_dir_escaped = f"{drive}\\:{rest}"
    else:
        fonts_dir_escaped = fonts_dir

    ass_filter_path = str(ass_path).replace("\\", "/")
    if ":" in ass_filter_path:
        drive, rest = ass_filter_path.split(":", 1)
        ass_filter_path = f"{drive}\\:{rest}"

    video_filter = (
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,eq=contrast=1.06:saturation=1.12,"
        f"subtitles='{ass_filter_path}':fontsdir='{fonts_dir_escaped}'[v]"
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

    log.info("Rendering %s with Anton 96pt -> %s...", vid, dest_video)
    subprocess.run(cmd, check=True)
    log.info("Completed: %s (%.2f MB)", dest_video.name, dest_video.stat().st_size / (1024 * 1024))

def main():
    log.info("=== RE-RENDERING BOTH VIDEOS WITH ANTON 96PT BOLD SUBTITLES ===")
    for vid, conf in VIDEOS_CONFIG.items():
        render_video(vid, conf)
    log.info("=== ALL COMPLETE ===")

if __name__ == "__main__":
    main()
