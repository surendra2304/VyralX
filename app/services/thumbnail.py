"""Deterministic thumbnail extraction using FFmpeg."""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.config import get_settings


def extract_thumbnail(render_path: str | Path, destination: str | Path, timestamp_seconds: float) -> str:
    settings = get_settings()
    source = Path(render_path).resolve()
    output = Path(destination).resolve()
    if not source.is_file():
        raise FileNotFoundError("Rendered video does not exist")
    if timestamp_seconds < 0:
        raise ValueError("Thumbnail timestamp must be non-negative")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y",
        "-ss", str(float(timestamp_seconds)), "-i", str(source),
        "-frames:v", "1", "-vf", "scale=1280:-2", "-q:v", "2", str(output),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Thumbnail extraction exceeded 45 seconds") from exc
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        raise RuntimeError((result.stderr or "FFmpeg thumbnail extraction failed")[-1500:])
    return str(output)
