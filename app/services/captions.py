"""Subtitle utilities for generated captions and explicit operator edits."""
from __future__ import annotations

import re
from pathlib import Path


def _timestamp(seconds: float) -> str:
    total_ms = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(segments: list[dict], destination: str | Path) -> Path:
    """Write plain-text SRT cues; strip markup and reject invalid cue ranges."""
    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    previous_start = -1.0
    for index, cue in enumerate(segments, start=1):
        start = float(cue["start_seconds"])
        end = float(cue["end_seconds"])
        text = str(cue["text"]).strip()
        if not text or start < 0 or end <= start:
            raise ValueError("Each caption requires text and a positive time range")
        if start < previous_start:
            raise ValueError("Caption segments must be ordered by start time")
        previous_start = start
        text = re.sub(r"<[^>]*>", "", text)
        text = text.replace("\x00", "")
        lines.extend([str(index), f"{_timestamp(start)} --> {_timestamp(end)}", text, ""])
    target.write_text("\n".join(lines), encoding="utf-8")
    return target
