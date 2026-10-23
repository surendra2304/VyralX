"""VyralX Frame-Perfect Synced Shorts Generator.

Upgrades:
1. WORD-LEVEL TIMESTAMPS: Uses edge_tts boundary='WordBoundary' to get exact
   millisecond start and duration for every single spoken word. Subtitles now sync
   100% frame-perfect with the voiceover.
2. WIDE UN-SQUEEZED FONT: Montserrat Black at 105pt (ScaleX: 100, Spacing: 0.5).
3. STYLING:
   - Outline: 5.5px pure black stroke
   - Shadow: 3.0px soft shadow
   - Colors: Pure White (&H00FFFFFF&) + Electric Cyan punch words (&H00FFE500&)
   - ZERO yellow text
4. PACING: 2-word bursts, positioned at MarginV=450.
5. NO 'SIR' in commentary. Voice: en-US-GuyNeural.
6. STRICT LOCAL OUTPUT: Saved directly to d:/FRIDAY Universe/VyralX/media/edited_videos/
7. ZERO UPLOADS.
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
log = logging.getLogger("vyralx.synced_shorts")

VIDEOS_CONFIG = {
    "A_Q2qpbHrqo": {
        "title": "When a 5-Star Michelin Restaurant Serves Soap Bubbles",
        "voice": "en-US-GuyNeural",
        "trim_duration": None,
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
        "trim_duration": 28.5,
        "script": (
            "When your friends try to roast you in the hallway, but you have maximum main character energy. "
            "While the rest of the squad is laughing and pointing fingers, she delivers the cleanest, most unimpressed eye-roll on the entire internet. "
            "And instead of arguing back, she just struts down the hallway like it is her personal fashion week runway. "
            "Zero hesitation, zero reaction, completely unbothered. That is how you own the entire room without saying a single word."
        ),
        "cyan_keywords": {
            "ROAST", "HALLWAY", "MAXIMUM", "MAIN", "CHARACTER", "ENERGY",
            "SQUAD", "CLEANEST", "EYE-ROLL", "INTERNET", "STRUTS", "RUNWAY",
            "HESITATION", "REACTION", "UNBOTHERED", "OWN", "ROOM"
        },
    },
}

def sec_to_ass(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:d}:{m:02d}:{sec:05.2f}"

async def generate_speech_with_word_sync(script: str, voice: str, audio_file: Path) -> list[dict[str, Any]]:
    # boundary='WordBoundary' sends millisecond timings for EVERY spoken word
    comm = edge_tts.Communicate(script, voice, boundary="WordBoundary")
    audio_bytes = b""
    words = []

    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio_bytes += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            st = chunk["offset"] / 1e7
            dur = chunk["duration"] / 1e7
            words.append({"text": chunk["text"], "start": st, "end": st + dur})

    audio_file.parent.mkdir(parents=True, exist_ok=True)
    audio_file.write_bytes(audio_bytes)
    log.info("Audio saved: %s (%d bytes, %d words detected)", audio_file.name, len(audio_bytes), len(words))

    # Group into tight 2-word bursts
    chunks = []
    i = 0
    while i < len(words):
        if i + 1 < len(words):
            pair = words[i:i+2]
            chunks.append({
                "text": f"{pair[0]['text']} {pair[1]['text']}",
                "start": pair[0]["start"],
                "end": pair[1]["end"]
            })
            i += 2
        else:
            single = words[i]
            chunks.append({
                "text": single["text"],
                "start": single["start"],
                "end": single["end"]
            })
            i += 1

    # Bridge small gaps (< 0.35s) so subtitle text doesn't flicker between words
    for j in range(len(chunks) - 1):
        gap = chunks[j+1]["start"] - chunks[j]["end"]
        if 0 < gap <= 0.35:
            chunks[j]["end"] = chunks[j+1]["start"]

    log.info("Built %d frame-synced subtitle cues (duration: %.2fs)", len(chunks), chunks[-1]["end"] if chunks else 0)
    return chunks

def create_ass_subtitles(cues: list[dict[str, Any]], cyan_words: set[str], ass_path: Path):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: WideSynced,Montserrat Black,105,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0.5,0,1,5.5,3.0,2,60,60,450,1

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
        events.append(f"Dialogue: 0,{st},{et},WideSynced,,0,0,0,,{line}")

    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text(header + "\n".join(events), encoding="utf-8")
    log.info("ASS Subtitles created: %s (%d events)", ass_path.name, len(events))

def render_video(vid: str, conf: dict[str, Any]):
    source = Path(f"media/viral_sources/{vid}.mp4").resolve()
    out_dir = Path("media/edited_videos").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    dest_video = out_dir / f"vyralx-commentary-{vid}.mp4"

    audio_path = Path(f"media/voiceovers/guy_synced_{vid}.mp3").resolve()
    ass_path = Path(f"media/voiceovers/subs_synced_{vid}.ass").resolve()

    # 1. Synthesize audio with word-level boundary sync
    cues = asyncio.run(generate_speech_with_word_sync(conf["script"], conf["voice"], audio_path))

    # 2. Build ASS with Montserrat Black 105pt
    create_ass_subtitles(cues, conf["cyan_keywords"], ass_path)

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
    ]

    if conf.get("trim_duration"):
        cmd.extend(["-t", str(conf["trim_duration"])])

    cmd.extend([
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
    ])

    log.info("Rendering %s with exact word sync -> %s...", vid, dest_video)
    subprocess.run(cmd, check=True)
    size_mb = dest_video.stat().st_size / (1024 * 1024)
    log.info("Rendering complete: %s (%.2f MB)", dest_video.name, size_mb)

def main():
    log.info("=================================================================")
    log.info("VYRALX: RENDERING EXACT WORD-SYNCED SHORTS (MONTSERRAT BLACK 105PT)")
    log.info("=================================================================")
    for vid, conf in VIDEOS_CONFIG.items():
        render_video(vid, conf)
    log.info("=================================================================")
    log.info("ALL RENDERS COMPLETED SUCCESSFULLY. NO UPLOADS PERFORMED.")
    log.info("=================================================================")

if __name__ == "__main__":
    main()
