"""Subtitle utilities for generated captions and explicit operator edits."""
from __future__ import annotations

import math
import re
from pathlib import Path


def _timestamp(seconds: float) -> str:
    total_ms = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(segments: list[dict], destination: str | Path) -> Path:
    """Write valid SRT cues, validating order/overlap at millisecond precision."""
    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    previous_start_ms = -1
    previous_end_ms = -1
    for index, cue in enumerate(segments, start=1):
        try:
            start = float(cue["start_seconds"])
            end = float(cue["end_seconds"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Each caption requires numeric start and end times") from None
        # Keep all cue text on a single logical line so untrusted text cannot
        # inject additional SRT cues or corrupt the subtitle structure.
        text = " ".join(
            re.sub(r"<[^>]*>", "", str(cue.get("text", ""))).replace("\x00", "").split()
        )
        if not math.isfinite(start) or not math.isfinite(end) or not text or start < 0 or end <= start:
            raise ValueError("Each caption requires text and a finite positive time range")

        # SRT timestamps only preserve milliseconds. Distinct float values can
        # collapse to the same timestamp or overlap when rounded for the file.
        start_ms = round(start * 1000)
        end_ms = round(end * 1000)
        if end_ms <= start_ms:
            raise ValueError("Caption cue must span at least 1 millisecond after SRT timestamp rounding")
        if start_ms < previous_start_ms:
            raise ValueError("Caption segments must be ordered by start time after SRT timestamp rounding")
        if start_ms < previous_end_ms:
            raise ValueError("Caption segments must not overlap after SRT timestamp rounding")

        previous_start_ms = start_ms
        previous_end_ms = end_ms
        lines.extend([
            str(index),
            f"{_timestamp(start_ms / 1000)} --> {_timestamp(end_ms / 1000)}",
            text,
            "",
        ])
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def segment_script(script: str, target_seconds: float, *, max_chars: int = 100) -> list[dict]:
    """Create timed captions without silently dropping words from long scripts.

    At most two cues per second are used. If a generated script needs more
    chunks, adjacent chunks are combined so all narration remains represented.
    """
    try:
        duration = float(target_seconds)
    except (TypeError, ValueError):
        raise ValueError("target_seconds must be a positive finite number") from None
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("target_seconds must be a positive finite number")
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
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

    max_cues = max(1, int(duration / 0.5))
    if len(chunks) > max_cues:
        group_size = math.ceil(len(chunks) / max_cues)
        chunks = [
            " ".join(chunks[start : start + group_size])
            for start in range(0, len(chunks), group_size)
        ]

    weights = [max(1, len(chunk.split())) for chunk in chunks]
    total_words = sum(weights)
    min_slot = min(0.5, duration / len(chunks))
    remaining = max(0.0, duration - min_slot * len(chunks))
    denominator = max(1, total_words)
    cursor = 0.0
    segments = []
    for index, chunk in enumerate(chunks):
        slot = min_slot + remaining * weights[index] / denominator
        start = cursor
        end = duration if index == len(chunks) - 1 else min(duration, cursor + slot)
        segments.append({
            "start_seconds": round(start, 3),
            "end_seconds": round(end, 3),
            "text": chunk,
        })
        cursor = end
    if segments:
        segments[-1]["end_seconds"] = round(duration, 3)
    return segments
