"""Frame analysis for the viral repurposing pipeline.

The commentary must describe what the clip actually shows. Text-only generation
cannot do that: given only a source title, the model invents a plot and the
voice-over ends up narrating something that never happens on screen.

This module samples three frames with ffmpeg and asks a vision model to describe
the visible action, so the editorial step has ground truth to work from. It is
best-effort: any failure returns an empty description and the pipeline falls
back to content-agnostic copy instead of blocking the upload.
"""
from __future__ import annotations

import base64
import logging
import subprocess
import tempfile
from pathlib import Path

import httpx

from app.config import get_settings

log = logging.getLogger("vyralx.scene_analysis")

# Positions through the clip: the setup, the middle beat and the payoff.
_FRAME_POSITIONS = (0.15, 0.5, 0.85)
_MAX_EDGE = 640

_PROMPT = (
    "These frames are sampled from one short vertical comedy clip, in order: "
    "frame 1 is the start, frame 2 the middle, frame 3 the end. "
    "For each frame describe exactly what is visible: the subject, what they are "
    "doing, and how the situation changes. Use only what you can see - never guess "
    "a joke, a line of dialogue or a detail that is not in the frames. "
    "Reply with exactly three numbered lines, one per frame, in this exact format "
    "and nothing else:\n"
    "1) <what is on screen in frame 1>\n"
    "2) <what is on screen in frame 2>\n"
    "3) <what is on screen in frame 3>\n"
    "Each line one short sentence, present tense. No preamble, no conclusion, no "
    "extra lines."
)


def _extract_frame(source: Path, seconds: float, destination: Path) -> bool:
    settings = get_settings()
    cmd = [
        settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{max(0.0, seconds):.2f}", "-i", str(source),
        "-frames:v", "1",
        "-vf", f"scale={_MAX_EDGE}:-2",
        "-q:v", "4",
        str(destination),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60, check=True)
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("Frame extraction failed at %.1fs: %s", seconds, exc)
        return False
    return destination.is_file() and destination.stat().st_size > 1_000


def _data_url(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def describe_scene(source_path: Path | str, duration: float) -> str:
    """Return a grounded description of the clip, or "" when vision is unavailable."""
    settings = get_settings()
    key = str(getattr(settings, "vision_api_key", "") or "").strip()
    if not key:
        return ""

    source = Path(source_path)
    if not source.is_file():
        return ""
    length = float(duration or 0.0)
    if length <= 0:
        return ""

    with tempfile.TemporaryDirectory(prefix="vyralx_frames_") as tmp:
        frames: list[Path] = []
        for index, position in enumerate(_FRAME_POSITIONS):
            destination = Path(tmp) / f"frame_{index}.jpg"
            if _extract_frame(source, length * position, destination):
                frames.append(destination)
        if not frames:
            return ""

        content: list[dict] = [{"type": "text", "text": _PROMPT}]
        for frame in frames:
            content.append({"type": "image_url", "image_url": {"url": _data_url(frame)}})

        body = {
            "model": settings.vision_model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2,
            "max_tokens": 300,
        }
        try:
            response = httpx.post(
                settings.vision_base_url.rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "User-Agent": "VyralX/1.0",
                },
                json=body,
                timeout=float(getattr(settings, "vision_timeout_seconds", 90)),
            )
            response.raise_for_status()
            payload = response.json()
            text = str(payload["choices"][0]["message"]["content"] or "").strip()
        except Exception as exc:  # noqa: BLE001 - vision must never block an upload
            log.warning("Scene analysis unavailable (%s: %s)", type(exc).__name__, str(exc)[:160])
            return ""

    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if text:
        log.info("Scene analysis: %s", text.replace("\\n", " | "))
    return text
