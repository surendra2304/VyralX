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


def segment_script(script: str, target_seconds: float, *, max_chars: int = 100) -> list[dict]:
    """Create ordered, approximate word-weighted caption timings for an original script."""
    import re

    if target_seconds <= 0:
        raise ValueError("target_seconds must be positive")
    text = " ".join(script.split())
    if not text:
        raise ValueError("Script cannot be empty")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    for sentence in sentences:
        words = sentence.split()
        current: list[str] = []
        for word in words:
            if current and len(" ".join(current + [word])) > max_chars:
                chunks.append(" ".join(current))
                current = []
            current.append(word)
        if current:
            chunks.append(" ".join(current))
    chunks = chunks[:max(1, int(target_seconds / 0.7))]
    weights = [max(1, len(chunk.split())) for chunk in chunks]
    total_words = sum(weights)
    min_slot = min(0.5, target_seconds / len(chunks))
    remaining = max(0.0, target_seconds - min_slot * len(chunks))
    denominator = max(1, total_words)
    cursor = 0.0
    segments = []
    for index, chunk in enumerate(chunks):
        duration = min_slot + remaining * weights[index] / denominator
        start = cursor
        end = target_seconds if index == len(chunks) - 1 else min(target_seconds, cursor + duration)
        segments.append({
            "start_seconds": round(start, 3),
            "end_seconds": round(end, 3),
            "text": chunk,
        })
        cursor = end
    # A dense script may leave small rounding artifacts at the end.
    if segments:
        segments[-1]["end_seconds"] = round(target_seconds, 3)
    return segments
