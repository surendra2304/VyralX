"""Subtitle utilities for generated captions and explicit operator edits."""
from __future__ import annotations

import math
import re
from pathlib import Path


ASS_STYLES: dict[str, dict] = {
    "ViralWhite": {
        "font": "Arial Black",
        "size": 78,
        "primary": "&H00FFFFFF",  # Pure Crisp White
        "secondary": "&H00FFFFFF",
        "outline": "&H00000000",   # Solid deep black outline
        "back": "&HB0000000",      # Deep shadow
        "bold": -1,
        "outline_width": 8,
        "shadow_depth": 4,
        "alignment": 2,            # Lower-third bottom-center
        "margin_v": 640,
        "highlight_color": "&H0000FFFF",  # Cyber Cyan accent for keywords
    },
    "CapCutViral": {
        "font": "Arial Black",
        "size": 78,
        "primary": "&H00FFFFFF",  # Crisp Modern White
        "secondary": "&H00FFFFFF",
        "outline": "&H00000000",   # Solid black outline
        "back": "&HB0000000",      # Deep shadow
        "bold": -1,
        "outline_width": 8,
        "shadow_depth": 4,
        "alignment": 2,            # Lower-third bottom-center
        "margin_v": 640,
        "highlight_color": "&H0000FF00",  # Neon Green pop
    },
    "CyberNeon": {
        "font": "Arial Black",
        "size": 76,
        "primary": "&H00FFFFFF",  # Crisp White
        "secondary": "&H00FFFF00",
        "outline": "&H00000000",  # Black outline
        "back": "&HA0000000",
        "bold": -1,
        "outline_width": 8,
        "shadow_depth": 4,
        "alignment": 2,
        "margin_v": 640,
        "highlight_color": "&H0000FFFF",
    },
    "CleanWhite": {
        "font": "Arial Black",
        "size": 78,
        "primary": "&H00FFFFFF",  # Pure White
        "secondary": "&H00FFFFFF",
        "outline": "&H00000000",  # Bold black outline
        "back": "&HA0000000",
        "bold": -1,
        "outline_width": 8,
        "shadow_depth": 4,
        "alignment": 2,
        "margin_v": 640,
        "highlight_color": "&H0000FFFF",
    },
    "ViralYellow": {
        "font": "Arial Black",
        "size": 78,
        "primary": "&H00FFFFFF",  # Modern White default
        "secondary": "&H00FFFFFF",
        "outline": "&H00000000",
        "back": "&HA0000000",
        "bold": -1,
        "outline_width": 8,
        "shadow_depth": 4,
        "alignment": 2,            # Lower-third bottom-center
        "margin_v": 640,
        "highlight_color": "&H0000FFFF",
    },
    "BoldRed": {
        "font": "Arial Black",
        "size": 78,
        "primary": "&H000000FF",  # Red (&H000000FF)
        "secondary": "&H00FFFFFF",
        "outline": "&H00000000",
        "back": "&HA0000000",
        "bold": -1,
        "outline_width": 8,
        "shadow_depth": 4,
        "alignment": 2,
        "margin_v": 640,
        "highlight_color": "&H00FFFFFF",
    },
}


def _timestamp(seconds: float) -> str:
    total_ms = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _ass_timestamp(seconds: float) -> str:
    total_cs = max(0, round(float(seconds) * 100))
    hours, remainder = divmod(total_cs, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


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


def write_ass(
    segments: list[dict],
    destination: str | Path,
    *,
    style: str = "ViralWhite",
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    highlight_keywords: list[str] | None = None,
    uppercase: bool = False,
) -> Path:
    """Write styled Advanced SubStation Alpha (.ass) subtitles with keyword emphasis."""
    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    style_name = style if style in ASS_STYLES else "ViralWhite"
    active_style = ASS_STYLES[style_name]
    keywords_set = {k.strip().lower() for k in (highlight_keywords or []) if k.strip()}

    events: list[str] = []
    previous_start_cs = -1
    previous_end_cs = -1

    for cue in segments:
        try:
            start = float(cue["start_seconds"])
            end = float(cue["end_seconds"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Each caption requires numeric start and end times") from None

        raw_text = str(cue.get("text", "")).replace("\x00", "").replace("{", "").replace("}", "")
        text = " ".join(re.sub(r"<[^>]*>", "", raw_text).split())
        if uppercase:
            text = text.upper()
        if not math.isfinite(start) or not math.isfinite(end) or not text or start < 0 or end <= start:
            raise ValueError("Each caption requires text and a finite positive time range")

        start_cs = round(start * 100)
        end_cs = round(end * 100)

        if end_cs <= start_cs:
            raise ValueError("Caption cue must span at least 1 centisecond after ASS timestamp rounding")
        if start_cs < previous_start_cs:
            raise ValueError("Caption segments must be ordered by start time after ASS timestamp rounding")
        if start_cs < previous_end_cs:
            raise ValueError("Caption segments must not overlap after ASS timestamp rounding")

        previous_start_cs = start_cs
        previous_end_cs = end_cs

        if keywords_set:
            words = text.split()
            formatted_words = []
            for w in words:
                clean_w = re.sub(r"[^\w]", "", w).lower()
                if clean_w in keywords_set:
                    formatted_words.append(f"{{\\c{active_style['highlight_color']}&}}{w}{{\\r}}")
                else:
                    formatted_words.append(w)
            dialogue_text = " ".join(formatted_words)
        else:
            dialogue_text = text

        start_str = _ass_timestamp(start_cs / 100)
        end_str = _ass_timestamp(end_cs / 100)
        events.append(f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{dialogue_text}")

    style_lines = [
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    ]
    for name, cfg in ASS_STYLES.items():
        style_lines.append(
            f"Style: {name},{cfg['font']},{cfg['size']},{cfg['primary']},{cfg['secondary']},"
            f"{cfg['outline']},{cfg['back']},{cfg['bold']},0,0,0,100,100,0,0,1,"
            f"{cfg['outline_width']},{cfg['shadow_depth']},{cfg['alignment']},40,40,{cfg['margin_v']},1"
        )

    doc = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {int(play_res_x)}",
        f"PlayResY: {int(play_res_y)}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        *style_lines,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *events,
        "",
    ]
    target.write_text("\n".join(doc), encoding="utf-8")
    return target


def segment_script(
    script: str,
    target_seconds: float,
    *,
    max_chars: int = 100,
    max_words_per_cue: int | None = None,
) -> list[dict]:
    """Create timed captions without silently dropping words from long scripts.

    At most two cues per second are used (or up to four when max_words_per_cue is specified).
    If a generated script needs more chunks, adjacent chunks are combined so all narration remains represented.
    """
    try:
        duration = float(target_seconds)
    except (TypeError, ValueError):
        raise ValueError("target_seconds must be a positive finite number") from None
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("target_seconds must be a positive finite number")
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if max_words_per_cue is not None and max_words_per_cue < 1:
        raise ValueError("max_words_per_cue must be positive")
    text = " ".join(script.split())
    if not text:
        raise ValueError("Script cannot be empty")
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    for sentence in sentences:
        words = sentence.split()
        current: list[str] = []
        for word in words:
            hit_word_limit = max_words_per_cue is not None and len(current) >= max_words_per_cue
            hit_char_limit = len(" ".join(current + [word])) > max_chars
            if current and (hit_word_limit or hit_char_limit):
                chunks.append(" ".join(current))
                current = []
            current.append(word)
        if current:
            chunks.append(" ".join(current))

    min_cue_slot = 0.25 if max_words_per_cue is not None else 0.5
    max_cues = max(1, int(duration / min_cue_slot))
    if len(chunks) > max_cues:
        group_size = math.ceil(len(chunks) / max_cues)
        chunks = [
            " ".join(chunks[start : start + group_size])
            for start in range(0, len(chunks), group_size)
        ]

    weights = [max(1, len(chunk.split())) for chunk in chunks]
    total_words = sum(weights)
    min_slot = min(min_cue_slot, duration / len(chunks))
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
