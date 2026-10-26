"""VyralX End-to-End Autonomous Video Production & Publishing Pipeline.

Coordinates the complete autonomous lifecycle:
1. Sourcing & Discovery: Ingests viral clips (high-retention, dialogue-free action/visuals).
2. Scriptwriting & Narration: Generates high-hook commentary (en-US-GuyNeural, zero "sir").
3. Word-Boundary Sync: Uses edge_tts WordBoundary for millisecond-accurate timing.
4. Styled ASS Subtitles: Un-squeezed Montserrat Black at 105pt, pure white + electric cyan.
5. Audio Mixing: Ducked ambient sound (20%) + Voice (100%) + EBU R128 loudnorm (-14 LUFS).
6. FFmpeg Vertical Composition: 1080x1920 @ 60fps with visual enhancements.
7. SEO Optimization: Viral title, hook description, debate question, tags.
8. Quota-Aware Publishing: Direct YouTube OAuth upload or graceful staging if daily limit is reached.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import edge_tts

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.services.visual_script_generator import analyze_video_frames
from app.services.youtube import upload_video

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [VyralX-Pipeline] %(message)s")
log = logging.getLogger("vyralx.pipeline")


@dataclass
class VideoJob:
    video_id: str
    source_file: Path
    title_concept: str
    script: str
    cyan_keywords: set[str]
    category_id: str = "24"
    trim_duration: float | None = None
    voice: str = "en-US-GuyNeural"
    tags: list[str] = field(default_factory=list)
    debate_question: str = ""
    privacy_status: str = "private"


def create_visual_job_from_source(source_file: Path, voice: str = "en-US-GuyNeural") -> VideoJob:
    """Uses multimodal vision AI to inspect video frames and create a grounded VideoJob."""
    log.info("Analyzing %s with Multimodal Vision AI...", source_file.name)
    analysis = analyze_video_frames(source_file, num_frames=4)
    return VideoJob(
        video_id=source_file.stem,
        source_file=source_file,
        title_concept=analysis.title,
        script=analysis.script,
        cyan_keywords=analysis.cyan_keywords,
        debate_question=analysis.debate_question,
        tags=analysis.tags,
        voice=voice,
        category_id="24"
    )


def sec_to_ass(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:d}:{m:02d}:{sec:05.2f}"


async def generate_speech_with_word_sync(script: str, voice: str, audio_file: Path) -> list[dict[str, Any]]:
    """Synthesizes speech and extracts exact millisecond word timestamps."""
    clean_script = (
        script.replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
    )
    comm = edge_tts.Communicate(clean_script, voice, boundary="WordBoundary")
    audio_bytes = b""
    words = []

    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio_bytes += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            st = chunk["offset"] / 1e7
            dur = chunk["duration"] / 1e7
            word_clean = (
                chunk["text"]
                .replace("\u2011", "-")
                .replace("\u2013", "-")
                .replace("\u2014", "-")
                .replace("’", "'")
            )
            words.append({"text": word_clean, "start": st, "end": st + dur})

    audio_file.parent.mkdir(parents=True, exist_ok=True)
    audio_file.write_bytes(audio_bytes)
    log.info("Audio rendered: %s (%d bytes, %d words detected)", audio_file.name, len(audio_bytes), len(words))

    # Assemble into 2-word bursts
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

    # Bridge small micro-gaps (< 0.35s) to eliminate subtitle flicker
    for j in range(len(chunks) - 1):
        gap = chunks[j+1]["start"] - chunks[j]["end"]
        if 0 < gap <= 0.35:
            chunks[j]["end"] = chunks[j+1]["start"]

    return chunks


def check_video_has_audio(file_path: Path) -> bool:
    """Checks if source video has an active audio stream."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(file_path)
        ]
        res = subprocess.check_output(cmd).decode().strip()
        return "audio" in res
    except Exception:
        return False


def get_video_dimensions(file_path: Path) -> tuple[int, int]:
    """Retrieves source video dimensions (width, height)."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            str(file_path)
        ]
        out = subprocess.check_output(cmd).decode().strip()
        parts = out.split("x")
        return int(parts[0]), int(parts[1])
    except Exception:
        return 1080, 1920


def get_ambient_bgm() -> Path | None:
    """Finds an ambient/upbeat background music track for silent clips."""
    import random
    candidates = []
    for dir_path in [Path("media/music"), Path("data/music"), PROJECT_ROOT / "media/music", PROJECT_ROOT / "data/music"]:
        if dir_path.exists():
            candidates.extend(list(dir_path.glob("*.mp3")) + list(dir_path.glob("*.m4a")))
    return random.choice(candidates) if candidates else None


def build_ass_subtitles(cues: list[dict[str, Any]], cyan_words: set[str], ass_path: Path):
    """Builds styled ASS subtitle file using punchy Anton Bold at 86pt with Shorts UI safe zone."""
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: AntonBold,Anton,86,&H00FFFFFF,&H000000FF,&H00000000,&HAA000000,0,0,0,0,100,100,1.2,0,1,5.5,3.0,2,80,80,380,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    cyan_code = r"{\c&H00FFE500&}"
    white_code = r"{\c&H00FFFFFF&}"

    for c in cues:
        st = sec_to_ass(c["start"])
        et = sec_to_ass(c["end"])
        clean_cue = c["text"].replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
        raw_words = clean_cue.upper().split()
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
    log.info("ASS Subtitles generated: %s (%d events, safe zone MarginV=380)", ass_path.name, len(events))


def render_video_job(job: VideoJob, output_dir: Path) -> Path:
    """Renders high-voltage vertical short with audio mastering, ducking, and adaptive framing."""
    output_dir.mkdir(parents=True, exist_ok=True)
    dest_video = output_dir / f"vyralx-commentary-{job.video_id}.mp4"

    voice_dir = Path("media/voiceovers").resolve()
    voice_dir.mkdir(parents=True, exist_ok=True)
    audio_path = voice_dir / f"voice_{job.video_id}.mp3"
    ass_path = voice_dir / f"subs_{job.video_id}.ass"

    # 1. Synthesize audio
    cues = asyncio.run(generate_speech_with_word_sync(job.script, job.voice, audio_path))

    render_duration = job.trim_duration
    if not render_duration and cues:
        render_duration = round(cues[-1]["end"] + 1.0, 2)

    # 2. Build ASS Subtitles
    build_ass_subtitles(cues, job.cyan_keywords, ass_path)

    # 3. Path escaping for libass
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

    # 4. Adaptive Framing (detect landscape vs portrait)
    width, height = get_video_dimensions(job.source_file)
    if width > height:
        log.info("Landscape video detected (%dx%d): Applying cinematic blurred background padding...", width, height)
        video_filter = (
            f"[0:v]split[bg][fg];"
            f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=22:22,eq=brightness=-0.12[blurred_bg];"
            f"[fg]scale=1080:-1[sharp_fg];"
            f"[blurred_bg][sharp_fg]overlay=(W-w)/2:(H-h)/2[base_v];"
            f"[base_v]subtitles='{ass_filter_path}':fontsdir='{fonts_dir_escaped}'[v]"
        )
    else:
        video_filter = (
            f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,eq=contrast=1.06:saturation=1.10,"
            f"subtitles='{ass_filter_path}':fontsdir='{fonts_dir_escaped}'[v]"
        )

    # 5. Dual-Layer Audio Mastering: preserve original sound ducked, or add BGM if silent
    has_audio = check_video_has_audio(job.source_file)
    bgm_track = None
    extra_inputs = []

    if has_audio:
        log.info("Source clip has original audio: Applying 22%% ducked mix under voiceover...")
        audio_filter = (
            "[0:a]volume=0.22[orig_a];"
            "[1:a]volume=1.0[voice_a];"
            "[orig_a][voice_a]amix=inputs=2:duration=first:dropout_transition=2,loudnorm=I=-14:LRA=9:TP=-1.5[a]"
        )
    else:
        bgm_track = get_ambient_bgm()
        if bgm_track:
            log.info("Silent source clip detected: Mixing ducked ambient track '%s' (14%% volume)...", bgm_track.name)
            extra_inputs.extend(["-stream_loop", "-1", "-i", str(bgm_track.resolve())])
            audio_filter = (
                "[2:a]volume=0.14[bgm_a];"
                "[1:a]volume=1.0[voice_a];"
                "[voice_a][bgm_a]amix=inputs=2:duration=first:dropout_transition=2,loudnorm=I=-14:LRA=9:TP=-1.5[a]"
            )
        else:
            log.info("Silent source with no BGM: Clean voice mastering...")
            audio_filter = "[1:a]volume=1.0,loudnorm=I=-14:LRA=9:TP=-1.5[a]"

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-y",
    ]

    if render_duration:
        cmd.extend(["-t", str(render_duration)])

    cmd.extend([
        "-i", str(job.source_file.resolve()),
        "-i", str(audio_path),
    ])
    cmd.extend(extra_inputs)
    cmd.extend([
        "-filter_complex", f"{video_filter};{audio_filter}",
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-r", "30",
        "-preset", "veryfast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(dest_video),
    ])

    log.info("Rendering %s -> %s...", job.video_id, dest_video.name)
    subprocess.run(cmd, check=True)
    size_mb = dest_video.stat().st_size / (1024 * 1024)
    log.info("Render complete: %s (%.2f MB)", dest_video.name, size_mb)
    return dest_video


def publish_or_stage(job: VideoJob, video_path: Path) -> dict[str, Any]:
    """Uploads video to YouTube as a draft (private) for review."""
    clean_title = job.title_concept.strip()
    if not clean_title.endswith("#shorts") and "#Shorts" not in clean_title and "#shorts" not in clean_title:
        clean_title = f"{clean_title} #Shorts"

    desc = (
        f"{job.script}\n\n"
        f"💬 QUESTION OF THE DAY: {job.debate_question}\n"
        f"Drop your answer below! 👇\n\n"
        f"🔔 SUBSCRIBE to @VyralXAgent for daily unhinged comedy & viral moments!\n\n"
        f"#Shorts #Viral #Trending #Entertainment #Comedy #Satisfying #Explore #Reels"
    )

    settings = get_settings()
    target_privacy = getattr(job, "privacy_status", None) or getattr(settings, "youtube_default_privacy", "private") or "private"

    log.info("Initiating upload for '%s' to DRAFTS (privacy: %s)...", clean_title, target_privacy)
    try:
        yt_id = upload_video(
            file_path=str(video_path),
            title=clean_title,
            description=desc,
            tags=job.tags or ["shorts", "viral", "trending", "comedy", "satisfying"],
            privacy_status=target_privacy,
            category_id=job.category_id,
        )
        watch_url = f"https://youtube.com/shorts/{yt_id}"
        log.info("DRAFT SAVED TO YOUTUBE! Watch URL: %s (Privacy: %s, Native video frame thumbnail)", watch_url, target_privacy)

        # Update published manifest
        manifest_path = Path("data/published_shorts_manifest.json")
        try:
            m_data = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
        except Exception:
            m_data = []
        m_data.append({
            "video_id": job.video_id,
            "yt_id": yt_id,
            "title": clean_title,
            "watch_url": watch_url,
            "privacy": target_privacy,
            "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "draft" if target_privacy == "private" else "published"
        })
        manifest_path.write_text(json.dumps(m_data, indent=2), encoding="utf-8")

        return {
            "video_id": job.video_id,
            "status": "draft" if target_privacy == "private" else "published",
            "youtube_id": yt_id,
            "watch_url": watch_url,
            "file": str(video_path),
            "privacy": target_privacy,
        }
    except Exception as e:
        err_str = str(e)
        if "uploadLimitExceeded" in err_str or "exceeded the number of videos" in err_str:
            log.warning("Daily upload limit reached on channel. Staging video locally for scheduled release.")
            return {
                "video_id": job.video_id,
                "status": "staged_quota_limited",
                "reason": "uploadLimitExceeded",
                "file": str(video_path)
            }
        elif "youtubeSignupRequired" in err_str:
            log.warning("Channel setup required on active account. Staging video locally.")
            return {
                "video_id": job.video_id,
                "status": "staged_signup_required",
                "reason": "youtubeSignupRequired",
                "file": str(video_path)
            }
        else:
            log.exception("Upload failed: %s", e)
            return {
                "video_id": job.video_id,
                "status": "failed",
                "error": err_str,
                "file": str(video_path)
            }


def run_pipeline(jobs: list[VideoJob]) -> list[dict[str, Any]]:
    output_dir = Path("media/edited_videos").resolve()
    results = []

    log.info("Starting autonomous production of %d videos...", len(jobs))
    for idx, job in enumerate(jobs, 1):
        log.info("=== [%d/%d] PROCESSING: %s ===", idx, len(jobs), job.title_concept)
        try:
            video_path = render_video_job(job, output_dir)
            pub_status = publish_or_stage(job, video_path)
            results.append(pub_status)
        except Exception as e:
            log.exception("Failed processing job %s: %s", job.video_id, e)
            results.append({
                "video_id": job.video_id,
                "status": "render_error",
                "error": str(e)
            })

    # Save execution manifest
    manifest_file = Path("data/autonomous_run_manifest.json")
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    log.info("Run manifest saved to %s", manifest_file)
    return results
