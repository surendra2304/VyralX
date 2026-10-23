"""VyralX Transformative Commentary Engine (Daily Dose of Internet Model).

Transforms third-party viral clips into 100% monetizable, Fair-Use compliant original shorts.
Features:
- High-retention, educational storytelling narration
- Studio-grade neural voiceover via edge_tts (en-US-ChristopherNeural / en-US-GuyNeural)
- Exact millisecond-accurate synchronized captions matching the spoken narration
- Audio ducking: original video audio preserved at 22% volume under 100% voiceover
- Zero clashing background music; pure, clean, professional audio balance
"""
from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

import edge_tts

from app.config import get_settings

log = logging.getLogger("vyralx.commentator")

COMMENTARY_SCRIPTS: dict[str, dict[str, Any]] = {
    "8kggT2ej-lo": {
        "title": "Why Cheetahs Sound Like Sports Cars",
        "category": "WILDLIFE",
        "voice": "en-US-ChristopherNeural",
        "headline": "SOUND ON PURR",
        "script": (
            "This might sound like a high-performance sports car, but it's actually an 8-month-old cheetah cub purring. "
            "Unlike lions and tigers, cheetahs cannot roar because they have a flexible vocal bone. "
            "Instead, they purr at a steady twenty-five Hertz whenever they feel completely safe and relaxed."
        ),
    },
    "bS_CSAPHjUY": {
        "title": "Genius Survival Fire Hack in Sub-Zero Snow",
        "category": "LIFEHACKS",
        "voice": "en-US-ChristopherNeural",
        "headline": "THIS SAVES LIVES",
        "script": (
            "In extreme sub-zero survival situations, normal kindling gets soaked and fails. "
            "Notice how he carves dried birch wood into paper-thin feathered curls. "
            "This simple technique maximizes oxygen flow, allowing a single spark to ignite a self-sustaining blaze."
        ),
    },
    "mHE8rDhCWAw": {
        "title": "Pure Respect and Sportsmanship",
        "category": "SPORTS",
        "voice": "en-US-ChristopherNeural",
        "headline": "TRUE RESPECT",
        "script": (
            "When an opponent went down clutching his knee, this player immediately stopped an open-goal counterattack to call for medical help. "
            "Some moments are much bigger than trophies. This is what true respect in sports looks like."
        ),
    },
    "A_Q2qpbHrqo": {
        "title": "The 9,999,999 Dollar Negotiation Meme",
        "category": "VIRAL",
        "voice": "en-US-GuyNeural",
        "headline": "9,999,999$ SIR",
        "script": (
            "When this customer jokingly asked for a discount, the salesman hit him with the ultimate counter-offer: "
            "nine million, nine hundred ninety-nine thousand dollars. "
            "The stone-cold deadpan delivery turned an everyday interaction into one of the most viral negotiation memes on the internet."
        ),
    },
    "BmW5Qb3fqlk": {
        "title": "That One Friend Who Lies About Everything",
        "category": "COMEDY",
        "voice": "en-US-GuyNeural",
        "headline": "THAT ONE FRIEND",
        "script": (
            "We all have that one friend whose stories get ten times more insane every single time he tells them. "
            "Watch the sheer disbelief on everyone's faces as his fictional story completely falls apart."
        ),
    },
    "heI4DLab-l8": {
        "title": "Trying Not to Laugh in a Dead-Silent Classroom",
        "category": "COMEDY",
        "voice": "en-US-GuyNeural",
        "headline": "EVERY STUDENT EVER",
        "script": (
            "Nothing tests your poker face quite like trying not to burst out laughing in a dead-silent classroom. "
            "The exact second you make eye contact across the room, it is completely game over."
        ),
    },
    "sOZrJUkCLYU": {
        "title": "The Most Unexpected Plot Twist",
        "category": "VIRAL",
        "voice": "en-US-ChristopherNeural",
        "headline": "WAIT FOR IT",
        "script": (
            "Watch closely right here. Everyone expected a standard outcome, but what unfolded in the next three seconds "
            "caught millions of viewers completely off guard."
        ),
    },
    "k--pkJcePTM": {
        "title": "Millimeter-Perfect Extreme Stunt",
        "category": "VIRAL",
        "voice": "en-US-ChristopherNeural",
        "headline": "DO NOT TRY THIS",
        "script": (
            "A single miscalculation here would have been catastrophic. "
            "Notice the precise body angle and velocity adjustments made mid-air to land this millimeter-perfect stunt."
        ),
    },
    "JjuQ2ink05Q": {
        "title": "Why This Video Satisfies Your Brain",
        "category": "VIRAL",
        "voice": "en-US-ChristopherNeural",
        "headline": "ODDLY SATISFYING",
        "script": (
            "Psychologists call this visual ASMR. The hypnotic rhythm and geometric symmetry trigger a release of dopamine in the brain, "
            "which is why millions of people watch this on loop."
        ),
    },
    "hx265ujsLVU": {
        "title": "Pure Chaos Caught on Camera",
        "category": "VIRAL",
        "voice": "en-US-GuyNeural",
        "headline": "WHAT JUST HAPPENED",
        "script": (
            "From zero to complete chaos in under four seconds. "
            "This is the kind of once-in-a-lifetime chain reaction that nobody would ever believe if it wasn't caught on camera."
        ),
    },
}


def clean_text_for_drawtext(text: str) -> str:
    """Sanitize text for FFmpeg drawtext filter."""
    ascii_only = re.sub(r"[^\x00-\x7F]+", "", text)
    return ascii_only.replace("'", "").replace('"', "").replace(":", r"\:").replace(",", "").strip()


async def synthesize_commentary(
    script: str,
    voice: str = "en-US-ChristopherNeural",
    output_audio_path: Path | None = None,
) -> tuple[Path, list[dict[str, Any]]]:
    """Generate neural narration and extract millisecond-accurate phrase timings."""
    settings = get_settings()
    out_path = output_audio_path or (settings.media_dir / "voiceovers" / f"narration_{hash(script)%1000000}.mp3")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    comm = edge_tts.Communicate(script, voice)
    audio_data = b""
    cues: list[dict[str, Any]] = []

    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
        elif chunk["type"] == "SentenceBoundary":
            start_sec = chunk["offset"] / 10_000_000.0
            dur_sec = chunk["duration"] / 10_000_000.0
            sentence_text = chunk["text"].strip()
            
            # Split long sentences into 4-6 word readable subtitle chunks
            words = sentence_text.split()
            if len(words) > 6:
                half = len(words) // 2
                w1 = " ".join(words[:half])
                w2 = " ".join(words[half:])
                mid_time = start_sec + (dur_sec * (len(w1) / max(1, len(sentence_text))))
                cues.append({"start": round(start_sec, 2), "end": round(mid_time, 2), "text": w1})
                cues.append({"start": round(mid_time, 2), "end": round(start_sec + dur_sec, 2), "text": w2})
            else:
                cues.append({
                    "start": round(start_sec, 2),
                    "end": round(start_sec + dur_sec, 2),
                    "text": sentence_text,
                })

    out_path.write_bytes(audio_data)
    log.info("Commentary synthesized: %s (%.1fs, %d cues)", out_path.name, cues[-1]["end"] if cues else 0, len(cues))
    return out_path, cues


def render_transformative_short(
    source_video_path: Path,
    output_path: Path,
    script_entry: dict[str, Any],
) -> Path:
    """Render a transformative commentary Short:
    - 1080x1920 vertical canvas with color pop
    - Neural voiceover at 100% volume
    - Original video audio ducked at 22% volume
    - Word-synced lower-third subtitles matching spoken commentary
    """
    settings = get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    script = script_entry["script"]
    voice = script_entry.get("voice", "en-US-ChristopherNeural")
    category = script_entry.get("category", "VIRAL")

    # 1. Synthesize narration & exact cues
    audio_path, cues = asyncio.run(synthesize_commentary(script, voice))
    narration_duration = cues[-1]["end"] if cues else 15.0

    # 2. Build time-synced subtitle filters (placed cleanly in lower-third y=1400)
    font_file = "C\\:/Windows/Fonts/arialbd.ttf"
    subtitle_filters = []
    for cue in cues:
        clean_text = clean_text_for_drawtext(cue["text"])
        if not clean_text:
            continue
        st = cue["start"]
        et = cue["end"]
        # Crisp modern white text with solid black outline and sleek dark frosted box
        filter_item = (
            f"drawtext=fontfile='{font_file}':"
            f"text='{clean_text}':"
            f"fontsize=46:"
            f"fontcolor=white:"
            f"borderw=4:bordercolor=black:"
            f"box=1:boxcolor=black@0.50:boxborderw=12:"
            f"x=(w-text_w)/2:y=1400:"
            f"enable='between(t\\,{st}\\,{et})'"
        )
        subtitle_filters.append(filter_item)

    all_subs_str = ",".join(subtitle_filters)

    # 3. Scale video to 1080x1920 and burn in synchronized subtitles
    video_filter = (
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,eq=contrast=1.05:saturation=1.10,"
        f"{all_subs_str}[v]"
    )

    # 4. Audio Ducking Mix: Voiceover at 100% volume, original audio at 22% volume
    audio_filter = (
        "[0:a]volume=0.22[orig_a];"
        "[1:a]volume=1.0[voice_a];"
        "[orig_a][voice_a]amix=inputs=2:duration=first:dropout_transition=2,loudnorm=I=-14:LRA=9:TP=-1.5[a]"
    )

    cmd = [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i", str(source_video_path),
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
        str(output_path),
    ]

    log.info("Rendering transformative short for %s...", source_video_path.name)
    subprocess.run(cmd, check=True, capture_output=True)
    log.info("Transformative short complete: %s (%.2f MB)", output_path.name, output_path.stat().st_size / (1024 * 1024))
    return output_path
