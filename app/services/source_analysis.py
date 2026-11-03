"""Source-clip analysis for the viral repurposing pipeline.

Everything here works offline with ffmpeg/ffprobe plus an optional local
Whisper model:

* :func:`probe_media` reports duration, resolution and whether the clip even
  carries an audio stream.
* :func:`detect_speech` decides whether the source already contains human
  narration. That decision drives the whole edit: narrated clips keep their own
  audio and get transcribed subtitles, silent/music clips get a fresh
  commentary voice-over instead. This is what stops two voices overlapping.
* :func:`download_audio_only` lets the pipeline audition a candidate cheaply
  before committing to a full video download.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yt_dlp

from app.config import get_settings
from app.services.ytdlp_support import apply_defaults

log = logging.getLogger("vyralx.source_analysis")

# Fragments Whisper emits for non-speech audio; they must never be treated as
# narration or used as subtitles.
_NON_SPEECH_TOKENS = {
    "music", "applause", "laughter", "laughs", "silence", "inaudible",
    "foreign", "sound", "noise", "blank_audio", " cheering", "cheering",
}


@dataclass(frozen=True)
class MediaProbe:
    duration: float
    width: int
    height: int
    has_audio: bool


@dataclass(frozen=True)
class SpeechReport:
    has_speech: bool
    speech_seconds: float
    cues: tuple[dict[str, Any], ...]
    text: str


def probe_media(path: Path | str) -> MediaProbe:
    """Return duration/resolution/audio-stream facts for a local media file."""
    settings = get_settings()
    cmd = [
        settings.ffprobe_bin, "-v", "error",
        "-show_entries", "stream=codec_type,width,height:format=duration",
        "-of", "json", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {Path(path).name}: {proc.stderr[-300:]}")
    payload = json.loads(proc.stdout or "{}")
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    try:
        duration = float((payload.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    return MediaProbe(
        duration=round(duration, 2),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        has_audio=has_audio,
    )


def measure_silence(path: Path | str, noise_db: int = -32, min_silence: float = 0.35) -> dict[str, float]:
    """Measure total silence so a mostly-dead clip can be rejected early."""
    settings = get_settings()
    cmd = [
        settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-i", str(path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    gaps = [float(value) for value in re.findall(r"silence_duration: ([0-9.]+)", proc.stderr)]
    probe = probe_media(path)
    total = sum(gaps)
    return {
        "duration": probe.duration,
        "silent_seconds": round(total, 2),
        "longest_gap": round(max(gaps) if gaps else 0.0, 2),
        "voiced_ratio": round(max(0.0, 1.0 - total / probe.duration), 3) if probe.duration else 0.0,
    }


@lru_cache(maxsize=2)
def _whisper(model_size: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_size, device="cpu", compute_type="int8")


def _is_speech_text(text: str) -> bool:
    cleaned = re.sub(r"[^\w'\s]", " ", (text or "").lower()).strip()
    if not cleaned:
        return False
    words = [w for w in cleaned.split() if w]
    if not words:
        return False
    # Auto-caption placeholders such as "[Music]" or "[Applause]".
    if len(words) <= 2 and all(w in _NON_SPEECH_TOKENS for w in words):
        return False
    return len(words) >= 2


def cues_from_segments(segments: list[Any], max_words: int = 5) -> list[dict[str, Any]]:
    """Split whisper/auto-caption segments into short, readable subtitle cues."""
    cues: list[dict[str, Any]] = []
    for segment in segments:
        text = " ".join(str(getattr(segment, "text", "") or "").split())
        if not _is_speech_text(text):
            continue
        start = float(getattr(segment, "start", 0.0) or 0.0)
        end = float(getattr(segment, "end", start + 1.0) or (start + 1.0))
        words = text.split()
        span = max(0.4, end - start)
        if len(words) <= max_words:
            cues.append({"start": round(start, 2), "end": round(end, 2), "text": text, "speech": True})
            continue
        total = max(1, len(words))
        for index in range(0, len(words), max_words):
            chunk = words[index:index + max_words]
            chunk_start = start + span * (index / total)
            chunk_end = start + span * (min(total, index + len(chunk)) / total)
            cues.append({
                "start": round(chunk_start, 2),
                "end": round(chunk_end, 2),
                "text": " ".join(chunk),
                "speech": True,
            })
    return cues


def detect_speech(path: Path | str, model_size: str = "base") -> SpeechReport:
    """Detect whether the clip already has narration, and transcribe it.

    Whisper runs behind a voice-activity filter so music and sound effects are
    not mistaken for speech. A clip only counts as narrated when at least one
    second of genuine speech is found.
    """
    settings = get_settings()
    probe = probe_media(path)
    if not probe.has_audio or probe.duration <= 0:
        return SpeechReport(False, 0.0, (), "")

    size = str(getattr(settings, "viral_whisper_model", "") or model_size or "base")
    try:
        model = _whisper(size)
    except Exception as exc:  # model download blocked -> stay conservative
        log.warning("Whisper unavailable (%s); assuming source has narration", type(exc).__name__)
        return SpeechReport(True, probe.duration, (), "")

    try:
        segments, _info = model.transcribe(
            str(path),
            beam_size=1,
            vad_filter=True,
            vad_parameters={"threshold": 0.35, "min_speech_duration_ms": 200},
            condition_on_previous_text=False,
        )
        segments = list(segments)
    except Exception as exc:
        log.warning("Speech detection failed (%s); assuming source has narration", type(exc).__name__)
        return SpeechReport(True, probe.duration, (), "")

    speech_seconds = 0.0
    kept = []
    for segment in segments:
        if not _is_speech_text(getattr(segment, "text", "") or ""):
            continue
        speech_seconds += max(0.0, float(getattr(segment, "end", 0.0)) - float(getattr(segment, "start", 0.0)))
        kept.append(segment)

    cues = cues_from_segments(kept)
    text = " ".join(cue["text"] for cue in cues).strip()
    has_speech = speech_seconds >= 1.0 and len(cues) >= 1
    log.info(
        "Speech analysis %s: has_speech=%s speech=%.1fs cues=%d",
        Path(path).name, has_speech, speech_seconds, len(cues),
    )
    return SpeechReport(has_speech, round(speech_seconds, 2), tuple(cues), text)


def download_audio_only(video_id: str, destination_dir: Path) -> Path | None:
    """Download just the audio track so a candidate can be auditioned cheaply."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    expected = destination_dir / f"{video_id}.m4a"
    if expected.is_file() and expected.stat().st_size > 10_000:
        return expected
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(destination_dir / f"{video_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }
    apply_defaults(opts)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    except Exception as exc:
        log.warning("Audio audition download failed for %s: %s", video_id, exc)
        return None
    for candidate in destination_dir.glob(f"{video_id}.*"):
        if candidate.suffix.lower() in {".m4a", ".webm", ".opus", ".mp3", ".aac"}:
            return candidate
    return None
