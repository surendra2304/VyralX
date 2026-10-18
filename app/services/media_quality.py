"""Signal-level FFmpeg checks for black frames, long silence, loudness and clipping."""
from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path
from typing import Any


_BLACK_RE = re.compile(
    r"black_start:(?P<start>-?\d+(?:\.\d+)?)\s+"
    r"black_end:(?P<end>-?\d+(?:\.\d+)?)\s+"
    r"black_duration:(?P<duration>-?\d+(?:\.\d+)?)"
)
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END_RE = re.compile(
    r"silence_end:\s*(-?\d+(?:\.\d+)?)\s*\|\s*"
    r"silence_duration:\s*(-?\d+(?:\.\d+)?)"
)
_LOUDNESS_RE = re.compile(r"\bI:\s*([-+]?\d+(?:\.\d+)?)\s*LUFS\b", re.IGNORECASE)
_TRUE_PEAK_RE = re.compile(r"\bPeak:\s*([-+]?\d+(?:\.\d+)?)\s*dBFS\b", re.IGNORECASE)
_CLIPPED_SAMPLES_RE = re.compile(r"Number of samples clipped:\s*(\d+)", re.IGNORECASE)
_BLACK_FILTER = "blackdetect=d=0.5:pix_th=0.10"
_SILENCE_FILTER = "silencedetect=n=-45dB:d=1.0"
_AUDIO_FILTER = (
    f"{_SILENCE_FILTER},astats=metadata=0:reset=0,"
    "ebur128=peak=true:framelog=verbose"
)


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _empty_audio_metrics(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "integrated_loudness_lufs": None,
        "true_peak_dbfs": None,
        "clipped_samples": None,
    }


def _parse_audio_metrics(log_text: str) -> dict[str, Any]:
    """Parse FFmpeg ebur128/astats summaries without treating missing metrics as zero."""
    loudness_values = [
        _finite_float(match.group(1), math.nan)
        for match in _LOUDNESS_RE.finditer(log_text)
    ]
    true_peak_values = [
        _finite_float(match.group(1), math.nan)
        for match in _TRUE_PEAK_RE.finditer(log_text)
    ]
    clipped_values = [
        int(match.group(1))
        for match in _CLIPPED_SAMPLES_RE.finditer(log_text)
    ]

    loudness = loudness_values[-1] if loudness_values and math.isfinite(loudness_values[-1]) else None
    true_peak = true_peak_values[-1] if true_peak_values and math.isfinite(true_peak_values[-1]) else None
    clipped_samples = clipped_values[-1] if clipped_values else None
    fully_analyzed = loudness is not None and true_peak is not None and clipped_samples is not None
    return {
        "status": "analyzed" if fully_analyzed else "partial",
        "integrated_loudness_lufs": round(loudness, 2) if loudness is not None else None,
        "true_peak_dbfs": round(true_peak, 2) if true_peak is not None else None,
        "clipped_samples": clipped_samples,
    }


def _unavailable(error_type: str, *, audio_analyzed: bool = False) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "error_type": error_type,
        "black_intervals": [],
        "silence_intervals": [],
        "audio_analyzed": audio_analyzed,
        "audio_metrics": _empty_audio_metrics("unavailable" if audio_analyzed else "not_applicable"),
        "thresholds": {
            "black_min_duration_seconds": 0.5,
            "silence_threshold_db": -45,
            "silence_min_duration_seconds": 1.0,
            "loudness_min_lufs": -24.0,
            "loudness_max_lufs": -10.0,
            "true_peak_max_dbfs": -1.0,
            "clipped_samples_max": 0,
        },
    }


def analyze_media_signals(
    video_path: str | Path,
    *,
    ffmpeg_bin: str = "ffmpeg",
    actual_duration: float,
    audio_stream_count: int,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Decode a completed render once with bounded black, silence, loudness and clipping filters.

    No output media is written. A failed or timed-out scan is reported as unavailable
    so production QA can surface an operator warning rather than silently passing.
    """
    path = Path(video_path)
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return _unavailable("missing_output")
    except (OSError, TypeError, ValueError):
        return _unavailable("missing_output")
    duration = _finite_float(actual_duration, -1.0)
    if duration <= 0:
        return _unavailable("invalid_duration")

    try:
        has_audio = int(audio_stream_count) > 0
    except (TypeError, ValueError):
        has_audio = False
    command = [
        str(ffmpeg_bin),
        "-hide_banner",
        "-nostats",
        "-v", "info",
        "-i", str(path),
        "-map", "0:v:0",
        "-vf", _BLACK_FILTER,
    ]
    if has_audio:
        command.extend(["-map", "0:a:0", "-af", _AUDIO_FILTER])
    command.extend(["-f", "null", "-"])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_seconds)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _unavailable("timeout", audio_analyzed=has_audio)
    except (OSError, ValueError):
        return _unavailable("ffmpeg_unavailable", audio_analyzed=has_audio)

    if result.returncode != 0:
        return _unavailable("ffmpeg_exit", audio_analyzed=has_audio)

    log_text = str(result.stderr or "")
    black_intervals: list[dict[str, float]] = []
    for match in _BLACK_RE.finditer(log_text):
        start = _finite_float(match.group("start"), -1.0)
        end = _finite_float(match.group("end"), -1.0)
        measured = _finite_float(match.group("duration"), -1.0)
        if start >= 0 and end > start and measured >= 0.5:
            black_intervals.append({
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "duration_seconds": round(measured, 3),
            })
        if len(black_intervals) >= 200:
            break

    silence_intervals: list[dict[str, float]] = []
    if has_audio:
        pending_start: float | None = None
        for line in log_text.splitlines():
            start_match = _SILENCE_START_RE.search(line)
            if start_match:
                pending_start = _finite_float(start_match.group(1), -1.0)
            end_match = _SILENCE_END_RE.search(line)
            if end_match:
                end = _finite_float(end_match.group(1), -1.0)
                measured = _finite_float(end_match.group(2), -1.0)
                start = pending_start if pending_start is not None and pending_start >= 0 else end - measured
                if start >= 0 and end > start and measured >= 1.0:
                    silence_intervals.append({
                        "start_seconds": round(start, 3),
                        "end_seconds": round(end, 3),
                        "duration_seconds": round(measured, 3),
                    })
                pending_start = None
                if len(silence_intervals) >= 200:
                    break
        if pending_start is not None and pending_start >= 0 and duration > pending_start:
            silence_intervals.append({
                "start_seconds": round(pending_start, 3),
                "end_seconds": round(duration, 3),
                "duration_seconds": round(duration - pending_start, 3),
            })

    return {
        "status": "analyzed",
        "error_type": None,
        "black_intervals": black_intervals,
        "silence_intervals": silence_intervals,
        "audio_analyzed": has_audio,
        "audio_metrics": _parse_audio_metrics(log_text) if has_audio else _empty_audio_metrics("not_applicable"),
        "thresholds": {
            "black_min_duration_seconds": 0.5,
            "silence_threshold_db": -45,
            "silence_min_duration_seconds": 1.0,
            "loudness_min_lufs": -24.0,
            "loudness_max_lufs": -10.0,
            "true_peak_max_dbfs": -1.0,
            "clipped_samples_max": 0,
        },
    }
