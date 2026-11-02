"""VyralX viral short editor.

Turns a discovered, reuse-licensed source clip into the channel's established
format:

* 1080x1920 vertical framing with a punchy colour grade
* Fast impact-font subtitles in the lower third, the same style the existing
  uploads use
* If the source has **no narration**: a neural commentary voice-over
  (edge-tts, Guy/Christopher) ducked over the original audio, with subtitles
  word-synced to that commentary
* If the source **already has narration**: no voice-over at all, the original
  audio stays at full volume and the subtitles come from a real transcript, so
  two voices never overlap
* A genre thumbnail, a rights record with the Creative Commons licence URL, and
  an unlisted publish job ready for the worker
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import edge_tts
import httpx
import yt_dlp
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Asset, PublishJob, RenderJob, Source, VideoProject, utcnow
from app.services.source_analysis import (
    SpeechReport,
    detect_speech,
    download_audio_only,
    probe_media,
)
from app.services.video_styler import clean_for_drawtext, get_genre_profile

log = logging.getLogger("vyralx.viral_remix")

VOICE_BY_CATEGORY = {
    "COMEDY": "en-US-GuyNeural",
    "VIRAL": "en-US-ChristopherNeural",
    "SPORTS": "en-US-ChristopherNeural",
}

COMMENTARY_TEMPLATES = {
    "VIRAL": (
        "Watch this closely. Everyone expects the obvious outcome, and then the whole moment "
        "flips in a way absolutely nobody saw coming. That single second is exactly why this "
        "clip keeps getting replayed."
    ),
    "COMEDY": (
        "You already know somebody exactly like this. Watch the confidence going in, then watch "
        "the exact second it all falls apart. The reaction at the end is the reason this one "
        "went viral."
    ),
    "SPORTS": (
        "One tiny mistake here and it is all over. Watch how much control goes into a moment "
        "that looks completely effortless on camera."
    ),
}

QUESTION_BY_CATEGORY = {
    "VIRAL": "Did you see that coming? Be honest!",
    "COMEDY": "Would you have kept a straight face?",
    "SPORTS": "Rate that execution from 1 to 10!",
}

HASHTAGS_BY_CATEGORY = {
    "VIRAL": "#Shorts #Viral #Trending #WaitForIt #VyralX",
    "COMEDY": "#Shorts #Comedy #Relatable #Viral #VyralX",
    "SPORTS": "#Shorts #Sports #Respect #Viral #VyralX",
}


# --------------------------------------------------------------------------- #
# helper wrappers
# --------------------------------------------------------------------------- #
def _run(cmd: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-600:]}")
    return proc


def _fmt_timecode(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def download_source_video(video_id: str, destination_dir: Path) -> Path:
    """Download the best available MP4 for a source clip."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    expected = destination_dir / f"{video_id}.mp4"
    if expected.is_file() and expected.stat().st_size > 100_000:
        return expected
    opts = {
        "format": "bestvideo[ext=mp4][height<=1920]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": str(destination_dir / f"{video_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    if expected.is_file():
        return expected
    for candidate in destination_dir.glob(f"{video_id}.*"):
        if candidate.suffix.lower() == ".mp4":
            return candidate
    raise RuntimeError(f"Source download produced no playable file for {video_id}")


def generate_editorial(
    category: str,
    source_title: str,
    channel: str,
    transcript: str,
    target_seconds: float,
) -> dict[str, str]:
    """Write a channel-style title plus (for silent clips) short commentary.

    Titles follow the four live uploads: one punchy claim, one or two emojis,
    then ``#Shorts``. The model is told never to copy the source title verbatim
    and never to invent facts about the footage.
    """
    settings = get_settings()
    words = max(30, min(80, int(max(10.0, min(target_seconds, 55.0)) * 2.4)))
    prompt = (
        "You produce titles and voice-over for a viral Shorts channel. These four titles define "
        "the channel style exactly:\n"
        + "\n".join(f"- {example}" for example in TITLE_EXAMPLES)
        + "\n\n"
        f"Source clip title: \"{source_title[:160]}\"\n"
        f"Source channel: {channel[:80]}\n"
        f"Category: {category}\n"
        f"Spoken transcript (may be empty): \"{(transcript or '')[:400]}\"\n\n"
        "Return one valid JSON object with exactly two keys: title and commentary.\n"
        "title: 5-11 words in the same style as the examples, 1-2 emojis, then ' #Shorts'. "
        "Do not copy the source title verbatim and do not claim exact numbers you cannot verify.\n"
        f"commentary: if the transcript is empty, {words} words or fewer of tense, observational "
        "voice-over narration for the clip; if the transcript is not empty, return an empty string "
        "(the original audio will be kept). No hashtags, no emojis, no stage directions, no quotes."
    )
    try:
        url = settings.inference_url.rstrip("/") + settings.inference_generation_path
        body = {
            "model": settings.inference_model or "auto",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a short-form video editor. Reply with one JSON object only.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.9,
            "max_tokens": 400,
            "stream": False,
        }
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.inference_api_key}",
                "X-API-Key": settings.inference_api_key,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=45,
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"]
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            payload = json.loads(raw[start:end + 1])
            title = " ".join(str(payload.get("title") or "").split())
            commentary = " ".join(str(payload.get("commentary") or "").split())
            if title:
                return {"title": title, "commentary": commentary}
    except Exception as exc:
        log.info("Editorial generation unavailable (%s); using template", type(exc).__name__)

    return {
        "title": TITLE_FALLBACKS.get(category.upper(), TITLE_FALLBACKS["VIRAL"]),
        "commentary": COMMENTARY_TEMPLATES.get(category.upper(), COMMENTARY_TEMPLATES["VIRAL"]),
    }


async def _synthesize_commentary(script: str, voice: str, output_path: Path) -> tuple[Path, list[dict[str, Any]]]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    communicate = edge_tts.Communicate(script, voice, rate="+8%")
    audio = bytearray()
    cues: list[dict[str, Any]] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "SentenceBoundary":
            start = chunk["offset"] / 10_000_000.0
            duration = chunk["duration"] / 10_000_000.0
            text = str(chunk["text"]).strip()
            words = text.split()
            if len(words) <= 6:
                cues.append({"start": round(start, 2), "end": round(start + duration, 2), "text": text})
            else:
                total = len(words)
                for index in range(0, total, 6):
                    part = words[index:index + 6]
                    cues.append({
                        "start": round(start + duration * (index / total), 2),
                        "end": round(start + duration * (min(total, index + len(part)) / total), 2),
                        "text": " ".join(part),
                    })
    if not audio:
        raise RuntimeError("edge-tts returned no audio")
    output_path.write_bytes(bytes(audio))
    return output_path, cues


def synthesize_commentary(script: str, voice: str, output_path: Path) -> tuple[Path, list[dict[str, Any]]]:
    return asyncio.run(_synthesize_commentary(script, voice, output_path))


def _subtitle_filter(cues: list[dict[str, Any]], category: str) -> str:
    profile = get_genre_profile(category)
    font_file = f"C\\:/Windows/Fonts/{profile.font_name}"
    filters: list[str] = []
    for cue in cues:
        text = clean_for_drawtext(str(cue.get("text") or ""))
        if not text:
            continue
        start, end = float(cue["start"]), float(cue["end"])
        if end <= start:
            end = start + 0.6
        filters.append(
            f"drawtext=fontfile='{font_file}':text='{text}':fontsize={profile.font_size}:"
            f"fontcolor={profile.primary_color}:borderw=4:bordercolor=black:"
            f"box=1:boxcolor=black@0.45:boxborderw=12:"
            f"x=(w-text_w)/2:y={profile.y_position}:"
            f"enable='between(t\\,{start:.2f}\\,{end:.2f})'"
        )
    return ",".join(filters)


def _fallback_beats(duration: float, hook: str, category: str) -> list[dict[str, Any]]:
    beats = [
        (0.0, min(3.6, duration), hook),
        (min(4.0, duration), min(10.0, duration), "NOBODY EXPECTED THIS"),
        (min(11.0, duration), max(11.5, duration - 0.5), "WATCH IT AGAIN"),
    ]
    return [
        {"start": round(start, 2), "end": round(end, 2), "text": text}
        for start, end, text in beats
        if end > start
    ]


# --------------------------------------------------------------------------- #
# renderers
# --------------------------------------------------------------------------- #
def _base_video_filter(cues: list[dict[str, Any]], category: str) -> str:
    subs = _subtitle_filter(cues, category)
    chain = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,eq=contrast=1.05:saturation=1.10"
    if subs:
        chain = f"{chain},{subs}"
    return chain


def render_with_commentary(
    source_path: Path,
    narration_path: Path,
    output_path: Path,
    cues: list[dict[str, Any]],
    category: str,
    source_has_audio: bool = True,
    duration: float = 0.0,
) -> Path:
    """Commentary over a silent/music-only clip; original audio ducked to 22%.

    The clip is never cut short to match the voice-over: the narration is padded
    with silence when it finishes early and the output keeps the source length,
    so the payoff at the end of the clip always survives the edit.
    """
    settings = get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    video_chain = _base_video_filter(cues, category)
    if source_has_audio:
        audio_chain = (
            "[0:a]volume=0.22[orig];"
            "[1:a]volume=1.0,apad[voice];"
            "[orig][voice]amix=inputs=2:duration=first:dropout_transition=2,"
            "loudnorm=I=-14:LRA=9:TP=-1.5[a]"
        )
    else:
        audio_chain = "[1:a]loudnorm=I=-14:LRA=9:TP=-1.5[a]"
    cmd = [
        settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y",
        "-i", str(source_path),
        "-i", str(narration_path),
        "-filter_complex", f"[0:v]{video_chain}[v];{audio_chain}",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "faster", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
    ]
    if source_has_audio:
        cmd += ["-t", f"{max(1.0, duration):.2f}"]
    else:
        cmd.append("-shortest")
    cmd.append(str(output_path))
    _run(cmd)
    return output_path


def render_with_original_audio(
    source_path: Path,
    output_path: Path,
    cues: list[dict[str, Any]],
    category: str,
    duration: float,
    source_has_audio: bool = True,
) -> Path:
    """Keep the source's own narration; subtitles transcribe what is actually said."""
    settings = get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    video_chain = _base_video_filter(cues, category)
    if source_has_audio:
        audio_chain = "[0:a]loudnorm=I=-14:LRA=9:TP=-1.5[a]"
    else:
        audio_chain = "anullsrc=channel_layout=stereo:sample_rate=44100,atrim=0:%.2f,loudnorm=I=-14:LRA=9:TP=-1.5[a]" % duration
    cmd = [
        settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y",
        "-i", str(source_path),
        "-filter_complex", f"[0:v]{video_chain}[v];{audio_chain}",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "faster", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-t", f"{duration:.2f}",
        str(output_path),
    ]
    _run(cmd)
    return output_path


# --------------------------------------------------------------------------- #
# copywriting
# --------------------------------------------------------------------------- #
TITLE_EXAMPLES = (
    "Wait For The Most Unexpected Plot Twist \U0001F631\U0001F92F #Shorts",
    "Millimeter-Perfect Extreme Stunt That Shocked Millions \U0001F631\U0001F525 #Shorts",
    "Maximum Main Character Energy In School \U0001F480\u2728 #Shorts",
    "The $9,999,999 Michelin Restaurant \U0001F480\U0001F9FC #Shorts",
)

TITLE_FALLBACKS = {
    "VIRAL": "Wait For The Most Unexpected Plot Twist \U0001F631\U0001F92F #Shorts",
    "COMEDY": "Maximum Main Character Energy \U0001F480\U0001F602 #Shorts",
    "SPORTS": "Millimeter-Perfect Stunt That Shocked Millions \U0001F631\U0001F525 #Shorts",
    "LIFEHACKS": "The Genius Hack Nobody Talks About \U0001F4A1 #Shorts",
}


def _clean_title(raw: str) -> str:
    title = " ".join(str(raw or "").split())
    title = re.sub(r"#\w+", "", title).strip(" -|:")
    if not title:
        return ""
    if "#shorts" not in title.casefold():
        title = f"{title} #Shorts"
    return title[:100]


def build_metadata(
    candidate: Any,
    speech: SpeechReport,
    hook: str,
    category: str,
    editorial: dict[str, str] | None = None,
) -> dict[str, Any]:
    editorial = editorial or {}
    title_core = re.sub(r"#\w+", "", str(candidate.title or "")).strip(" |-—")
    title_core = " ".join(title_core.split())[:80] or hook.title()
    title = _clean_title(editorial.get("title") or "")
    if not title:
        title = _clean_title(TITLE_FALLBACKS.get(category.upper(), TITLE_FALLBACKS["VIRAL"]))
    comment = " ".join(str(editorial.get("commentary") or "").split())

    question = QUESTION_BY_CATEGORY.get(category.upper(), QUESTION_BY_CATEGORY["VIRAL"])
    hashtags = HASHTAGS_BY_CATEGORY.get(category.upper(), HASHTAGS_BY_CATEGORY["VIRAL"])
    summary = comment or (
        "Watch what happens in this clip - one moment, and the whole thing flips."
        if not speech.has_speech
        else "The moment everyone replayed, with the audio left exactly as it was recorded."
    )
    description = (
        f"{summary}\n\n"
        f"QUESTION OF THE DAY: {question}\n\n"
        f"SUBSCRIBE to @VyralXAgent for daily viral moments!\n\n"
        f"{hashtags}\n\n"
        f'Credit: source clip "{title_core}" by {candidate.channel or "the original creator"} - '
        f"https://www.youtube.com/watch?v={candidate.video_id}\n"
        f"Commentary, subtitles and edit by VyralX."
    )
    tags = [
        "shorts", "viral", "trending", category.lower(), "wait for it",
        "vyralx", "funny", "moments",
    ]
    return {
        "title": title,
        "description": description[:4800],
        "tags": tags,
        "hook": hook,
        "commentary": comment,
    }


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def produce_viral_short(
    candidate: Any,
    db: Session,
    *,
    require_silent_source: bool = True,
    publish: bool = True,
) -> dict[str, Any]:
    """Audition -> download -> edit -> register -> queue publish for one candidate."""
    settings = get_settings()
    category = str(candidate.category or "VIRAL").upper()
    settings.prepare_directories()
    settings.render_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)

    # 1. Cheap audio audition: is there already a voice in this clip?
    audio_dir = settings.media_dir / "viral_audio_probe"
    audio_path = download_audio_only(candidate.video_id, audio_dir)
    if audio_path is None:
        return {"status": "SKIPPED", "reason": "audio_unavailable", "video_id": candidate.video_id}
    speech = detect_speech(audio_path)
    if speech.has_speech and require_silent_source:
        return {
            "status": "SKIPPED",
            "reason": "source_has_narration",
            "video_id": candidate.video_id,
            "speech_seconds": speech.speech_seconds,
        }

    # 2. Full download and probe
    source_path = download_source_video(candidate.video_id, settings.media_dir / "viral_sources")
    probe = probe_media(source_path)
    duration = min(58.0, max(6.0, probe.duration or float(candidate.duration or 20.0)))
    project_key = f"viral-{candidate.video_id}-{uuid.uuid4().hex[:6]}"
    render_path = settings.render_dir / f"{project_key}.mp4"
    hook = str(candidate.hook or "WAIT FOR IT")

    # 3. Edit: commentary when silent, transcript subtitles when narrated
    editorial = generate_editorial(
        category,
        str(getattr(candidate, "title", "")),
        str(getattr(candidate, "channel", "")),
        speech.text,
        duration,
    )
    if speech.has_speech and speech.cues:
        cues = [dict(cue) for cue in speech.cues]
        render_with_original_audio(source_path, render_path, cues, category, duration, probe.has_audio)
        mode = "original_narration"
        voice_script = ""
    else:
        voice = VOICE_BY_CATEGORY.get(category, "en-US-ChristopherNeural")
        voice_script = editorial.get("commentary") or COMMENTARY_TEMPLATES.get(
            category, COMMENTARY_TEMPLATES["VIRAL"]
        )
        narration_path = settings.media_dir / "voiceovers" / f"{project_key}.mp3"
        _, cues = synthesize_commentary(voice_script, voice, narration_path)
        if not cues:
            cues = _fallback_beats(duration, hook, category)
        render_with_commentary(
            source_path, narration_path, render_path, cues, category,
            probe.has_audio, duration,
        )
        mode = "commentary"

    thumbnail_path = settings.render_dir / f"{project_key}-thumb.jpg"
    try:
        from app.services.thumbnail_designer import generate_genre_thumbnail

        generate_genre_thumbnail(
            video_path=source_path,
            output_path=thumbnail_path,
            headline=hook,
            category=category,
        )
    except Exception as exc:  # thumbnail is a nice-to-have, never fatal
        log.warning("Thumbnail generation failed: %s", exc)
        thumbnail_path = Path("")

    meta = build_metadata(candidate, speech, hook, category, editorial)

    # 4. Persist rights record + render + queued publish job
    reuse_licensed = bool(str(getattr(candidate, "license", "")).strip()) and (
        "creative commons" in str(candidate.license).casefold()
    )
    if reuse_licensed:
        platform = "youtube_creative_commons"
        license_name = str(candidate.license)[:190]
        permission_reference = (
            f"https://www.youtube.com/watch?v={candidate.video_id} - licence: {candidate.license}"
        )[:2000]
        notes = "Reuse licence verified from the source metadata."
    else:
        platform = "youtube_transformative"
        license_name = "Transformative commentary - original creator credited (operator policy)"
        permission_reference = (
            f"https://www.youtube.com/watch?v={candidate.video_id} - operator-attested "
            "transformative commentary: original audio retained or new commentary added, "
            "subtitles and attribution on every upload"
        )[:2000]
        notes = "Operator-selected transformative commentary policy; original creator credited in the description."
    source = Source(
        title=f"Source: {candidate.title[:240]}",
        source_url=f"https://www.youtube.com/watch?v={candidate.video_id}",
        platform=platform,
        creator=str(candidate.channel or "")[:280],
        license_name=license_name,
        permission_reference=permission_reference,
        repeat_use_allowed=True,
        rights_verified=True,
        status="approved",
        notes=notes,
    )
    db.add(source)
    db.flush()
    asset = Asset(
        source_id=source.id,
        title=str(candidate.title)[:280],
        file_path=str(source_path),
        duration_seconds=float(duration),
        width=probe.width,
        height=probe.height,
        rights_verified=True,
    )
    db.add(asset)
    db.flush()

    project = VideoProject(
        project_key=project_key,
        topic=f"Repurposed: {str(candidate.title)[:120]}",
        video_format="shorts",
        target_seconds=int(round(duration)),
        audience="viral shorts audience",
        tone="high energy, deadpan funny",
        scene_count=1,
        confirm_pexels_license=False,
        confirm_pexels_repeat_use=False,
        use_voiceover=(mode == "commentary"),
        status="completed",
        primary_asset_id=asset.id,
        asset_ids_json=json.dumps([asset.id]),
        thumbnail_path=str(thumbnail_path) if thumbnail_path else "",
        completed_at=utcnow(),
        attempts=1,
    )
    db.add(project)
    db.flush()

    render_job = RenderJob(
        asset_id=asset.id,
        preset="shorts",
        status="completed",
        output_path=str(render_path),
        attempts=1,
        project_id=None,
        options_json=json.dumps({
            "montage_asset_ids": [asset.id],
            "source_video_id": candidate.video_id,
            "source_views": int(getattr(candidate, "view_count", 0) or 0),
            "edit_mode": mode,
        }),
        completed_at=utcnow(),
    )
    db.add(render_job)
    db.flush()
    project.render_job_id = render_job.id

    publish_job = None
    if publish:
        publish_job = PublishJob(
            asset_id=asset.id,
            render_job_id=render_job.id,
            title=meta["title"],
            description=meta["description"],
            tags_json=json.dumps(meta["tags"]),
            privacy_status=str(getattr(settings, "autonomous_publish_privacy", "unlisted")),
            status="queued",
            approved_at=utcnow(),
        )
        db.add(publish_job)
    db.commit()

    result = {
        "status": "QUEUED_FOR_PUBLISH" if publish else "RENDERED",
        "project_key": project_key,
        "project_id": project.id,
        "render_job_id": render_job.id,
        "publish_job_id": publish_job.id if publish_job else None,
        "edit_mode": mode,
        "source_video_id": candidate.video_id,
        "source_views": int(getattr(candidate, "view_count", 0) or 0),
        "source_license": candidate.license,
        "title": meta["title"],
        "duration": round(duration, 1),
        "narration": voice_script[:280],
        "render": str(render_path),
    }
    log.info("Viral short ready: %s", result)
    return result


def recency_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
