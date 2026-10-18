"""Lightweight, auditable production QA for completed topic-to-video projects."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any


def _has_file(value: str | Path | None) -> bool:
    if not value:
        return False
    try:
        path = Path(value)
        return path.is_file() and path.stat().st_size > 0
    except (OSError, TypeError, ValueError):
        return False


def _words(value: str) -> list[str]:
    return re.findall(r"\w+", str(value or "").casefold(), flags=re.UNICODE)


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_project_quality_report(
    *,
    target_seconds: int,
    actual_duration: float,
    expected_width: int,
    expected_height: int,
    actual_width: int,
    actual_height: int,
    audio_stream_count: int,
    voiceover_requested: bool,
    voiceover_path: str | Path | None,
    voiceover_duration: float | None,
    subtitle_path: str | Path | None,
    subtitle_segments: list[dict[str, Any]],
    caption_text: str,
    thumbnail_path: str | Path | None,
    scene_rights_checks: list[bool],
    signal_analysis: dict[str, Any] | None = None,
    caption_alignment_status: str = "estimated",
) -> dict[str, Any]:
    """Return a QA snapshot. Warnings require operator attention, never auto-approval."""
    checks: list[dict[str, Any]] = []

    def add(check_id: str, label: str, passed: bool | None, message: str, actual: Any = None, expected: Any = None) -> None:
        status = "not_applicable" if passed is None else ("passed" if passed else "warning")
        check: dict[str, Any] = {"id": check_id, "label": label, "status": status, "message": message}
        if actual is not None:
            check["actual"] = actual
        if expected is not None:
            check["expected"] = expected
        checks.append(check)

    duration_ok = (
        math.isfinite(float(actual_duration))
        and actual_duration > 0
        and abs(float(actual_duration) - int(target_seconds)) <= 1.5
    )
    add(
        "duration", "Rendered duration", duration_ok,
        "Rendered duration is within 1.5 seconds of target." if duration_ok else "Rendered duration differs from target by more than 1.5 seconds.",
        round(float(actual_duration), 3) if math.isfinite(float(actual_duration)) else None,
        int(target_seconds),
    )
    dimensions_ok = int(actual_width) == int(expected_width) and int(actual_height) == int(expected_height)
    add(
        "dimensions", "Output dimensions", dimensions_ok,
        "Output matches the selected preset." if dimensions_ok else "Output dimensions do not match the selected preset.",
        f"{int(actual_width)}x{int(actual_height)}", f"{int(expected_width)}x{int(expected_height)}",
    )

    if voiceover_requested:
        audio_ok = int(audio_stream_count) > 0
        add("audio_track", "Narration track", audio_ok,
            "An audio stream is present." if audio_ok else "Narration was requested but no audio stream was detected.",
            int(audio_stream_count), "at least 1 audio stream")
        voice_ok = _has_file(voiceover_path)
        add("narration_file", "Narration asset", voice_ok,
            "Narration file exists and is non-empty." if voice_ok else "Narration file is missing or empty.",
            "present" if voice_ok else "missing", "non-empty audio file")
        try:
            measured_voiceover_seconds = float(voiceover_duration)
        except (TypeError, ValueError):
            measured_voiceover_seconds = math.nan
        minimum_voiceover_seconds = int(target_seconds) * 0.75
        maximum_voiceover_seconds = int(target_seconds) + 1.5
        voiceover_duration_ok = (
            math.isfinite(measured_voiceover_seconds)
            and measured_voiceover_seconds > 0
            and minimum_voiceover_seconds <= measured_voiceover_seconds <= maximum_voiceover_seconds
        )
        add(
            "voiceover_duration", "Narration timing", voiceover_duration_ok,
            "Narration duration fits the target window." if voiceover_duration_ok
            else "Narration is substantially shorter than the target or exceeds it; review script density and timing.",
            round(measured_voiceover_seconds, 3) if math.isfinite(measured_voiceover_seconds) else None,
            f"{minimum_voiceover_seconds:.1f}–{maximum_voiceover_seconds:.1f} seconds",
        )
    else:
        add("audio_track", "Narration track", None, "Narration was not requested.")
        add("voiceover_duration", "Narration timing", None, "Narration was not requested.")

    subtitle_ok = _has_file(subtitle_path) and bool(subtitle_segments)
    add("subtitle_file", "Caption file", subtitle_ok,
        "SRT file and caption cues exist." if subtitle_ok else "SRT file or caption cues are missing.",
        len(subtitle_segments), "at least 1 cue")
    spoken_words = _words(caption_text)
    caption_words = _words(" ".join(str(cue.get("text") or "") for cue in subtitle_segments if isinstance(cue, dict)))
    coverage_ok = bool(spoken_words) and spoken_words == caption_words
    add("caption_coverage", "Caption word coverage", coverage_ok,
        "Caption cues preserve all spoken-script words in order." if coverage_ok else "Caption text differs from the narration script; review wording and coverage.",
        len(caption_words), len(spoken_words))

    timing_ok = bool(subtitle_segments)
    expected_caption_end = float(target_seconds)
    expected_caption_end_label = "target duration"
    if voiceover_requested and caption_alignment_status == "measured_chunk":
        measured_duration = _finite_number(voiceover_duration)
        if measured_duration is not None and measured_duration > 0:
            expected_caption_end = measured_duration
            expected_caption_end_label = "measured narration duration"
    previous_end = 0.0
    for index, cue in enumerate(subtitle_segments):
        try:
            start = float(cue["start_seconds"])
            end = float(cue["end_seconds"])
        except (KeyError, TypeError, ValueError):
            timing_ok = False
            break
        if (not math.isfinite(start) or not math.isfinite(end) or start < previous_end
                or end <= start or not str(cue.get("text") or "").strip()):
            timing_ok = False
            break
        if index == 0 and start > 0.05:
            timing_ok = False
            break
        previous_end = end
    timing_ok = timing_ok and abs(previous_end - expected_caption_end) <= 0.05
    add("caption_timing", "Caption timing", bool(timing_ok),
        f"Caption cues are ordered, non-overlapping, and span the {expected_caption_end_label}."
        if timing_ok else f"Caption cues have invalid timing or do not span the {expected_caption_end_label}.",
        round(previous_end, 3), round(expected_caption_end, 3))

    if not voiceover_requested:
        add("caption_sync", "Caption-to-speech alignment", None, "Narration was not requested.")
    elif caption_alignment_status == "measured_chunk":
        add(
            "caption_sync", "Caption-to-speech alignment", bool(subtitle_segments),
            "Caption boundaries follow measured per-chunk narration durations; this is phrase-level alignment, not word-level forced alignment."
            if subtitle_segments else "Measured narration alignment has no caption cues.",
            caption_alignment_status, "measured chunk-level narration timing",
        )
    else:
        add(
            "caption_sync", "Caption-to-speech alignment", False,
            "Caption timings are estimated rather than derived from measured narration chunks; review playback and align cues before publishing.",
            caption_alignment_status or "unknown", "measured chunk-level narration timing",
        )

    thumbnail_ok = _has_file(thumbnail_path)
    add("thumbnail", "Thumbnail output", thumbnail_ok,
        "Thumbnail exists and is non-empty." if thumbnail_ok else "Thumbnail output is missing or empty.",
        "present" if thumbnail_ok else "missing", "non-empty image")

    rights_ok = bool(scene_rights_checks) and all(bool(value) for value in scene_rights_checks)
    add("scene_provenance", "Scene provenance", rights_ok,
        "Every scene passed automated provenance checks." if rights_ok else "At least one scene lacks a passing source-evidence check.",
        sum(bool(value) for value in scene_rights_checks), len(scene_rights_checks))

    if signal_analysis is None:
        add(
            "black_frames", "Black-frame scan", False,
            "Signal-level media analysis was not supplied; inspect the rendered video manually.",
            "not supplied", "completed signal scan",
        )
        if int(audio_stream_count) > 0:
            add("silence_gaps", "Silence-gap scan", False, "Signal-level audio analysis was not supplied.")
            add("audio_loudness", "Loudness / true-peak scan", False, "Audio loudness measurements were not supplied.")
            add("audio_clipping", "Clipping scan", False, "Audio clipping measurements were not supplied.")
        else:
            add("silence_gaps", "Silence-gap scan", None, "The render has no audio stream to analyze.")
            add("audio_loudness", "Loudness / true-peak scan", None, "The render has no audio stream to analyze.")
            add("audio_clipping", "Clipping scan", None, "The render has no audio stream to analyze.")
    elif signal_analysis.get("status") != "analyzed":
        error_type = signal_analysis.get("error_type") or "unavailable"
        add(
            "black_frames", "Black-frame scan", False,
            "FFmpeg signal analysis was unavailable; inspect the video manually.",
            error_type, "completed signal scan",
        )
        if int(audio_stream_count) > 0:
            add(
                "silence_gaps", "Silence-gap scan", False,
                "FFmpeg audio analysis was unavailable; inspect narration and silence manually.",
                error_type, "completed audio scan",
            )
            add("audio_loudness", "Loudness / true-peak scan", False, "FFmpeg audio loudness analysis was unavailable.", error_type, "complete audio metrics")
            add("audio_clipping", "Clipping scan", False, "FFmpeg clipping analysis was unavailable.", error_type, "complete clipping metrics")
        else:
            add("silence_gaps", "Silence-gap scan", None, "The render has no audio stream to analyze.")
            add("audio_loudness", "Loudness / true-peak scan", None, "The render has no audio stream to analyze.")
            add("audio_clipping", "Clipping scan", None, "The render has no audio stream to analyze.")
    else:
        raw_black = signal_analysis.get("black_intervals")
        black_intervals = raw_black if isinstance(raw_black, list) else []
        valid_black = []
        for interval in black_intervals[:200]:
            if not isinstance(interval, dict):
                continue
            duration = _finite_number(interval.get("duration_seconds"))
            if duration is not None and duration >= 0.5:
                valid_black.append(interval)
        add(
            "black_frames", "Black-frame scan", not valid_black,
            "No sustained black frames were detected." if not valid_black
            else "Sustained black-frame intervals were detected; inspect the rendered video.",
            {"count": len(valid_black), "intervals": valid_black[:20]},
            "no intervals >= 0.5 seconds",
        )

        if int(audio_stream_count) <= 0:
            add("silence_gaps", "Silence-gap scan", None, "The render has no audio stream to analyze.")
            add("audio_loudness", "Loudness / true-peak scan", None, "The render has no audio stream to analyze.")
            add("audio_clipping", "Clipping scan", None, "The render has no audio stream to analyze.")
        elif not bool(signal_analysis.get("audio_analyzed")):
            add(
                "silence_gaps", "Silence-gap scan", False,
                "The signal analysis did not inspect the rendered audio stream.",
                "not analyzed", "audio scan completed",
            )
            add("audio_loudness", "Loudness / true-peak scan", False, "The signal analysis did not inspect the rendered audio stream.")
            add("audio_clipping", "Clipping scan", False, "The signal analysis did not inspect the rendered audio stream.")
        else:
            raw_silence = signal_analysis.get("silence_intervals")
            silence_intervals = raw_silence if isinstance(raw_silence, list) else []
            silence_threshold = max(2.0, int(target_seconds) * 0.08)
            long_silence = []
            longest_silence = 0.0
            for interval in silence_intervals[:200]:
                if not isinstance(interval, dict):
                    continue
                duration = _finite_number(interval.get("duration_seconds"))
                if duration is None or duration < 0:
                    continue
                longest_silence = max(longest_silence, duration)
                if duration > silence_threshold:
                    long_silence.append(interval)
            add(
                "silence_gaps", "Silence-gap scan", not long_silence,
                "No unusually long silence gaps were detected." if not long_silence
                else "Long silence gaps were detected; confirm that pauses and narration match the intended edit.",
                {"count": len(long_silence), "longest_seconds": round(longest_silence, 3),
                 "intervals": long_silence[:20]},
                f"no gaps > {silence_threshold:.1f} seconds",
            )

            raw_metrics = signal_analysis.get("audio_metrics")
            metrics = raw_metrics if isinstance(raw_metrics, dict) else {}
            integrated = _finite_number(metrics.get("integrated_loudness_lufs"))
            true_peak = _finite_number(metrics.get("true_peak_dbfs"))
            clipped_samples = _finite_number(metrics.get("clipped_samples"))
            min_loudness = -24.0
            max_loudness = -10.0
            max_true_peak = -1.0
            loudness_complete = integrated is not None and true_peak is not None
            loudness_ok = (
                loudness_complete
                and min_loudness <= integrated <= max_loudness
                and true_peak <= max_true_peak
            )
            if not loudness_complete:
                loudness_message = "FFmpeg did not return complete integrated-loudness and true-peak measurements; review the audio manually."
            elif loudness_ok:
                loudness_message = "Integrated loudness and true peak are within the broad review thresholds."
            else:
                loudness_message = "Integrated loudness or true peak is outside the review thresholds; adjust levels and listen back."
            add(
                "audio_loudness", "Loudness / true-peak scan", bool(loudness_ok),
                loudness_message,
                {
                    "integrated_loudness_lufs": integrated,
                    "true_peak_dbfs": true_peak,
                },
                {
                    "integrated_loudness_lufs": f"{min_loudness:.0f} to {max_loudness:.0f}",
                    "true_peak_dbfs": f"<= {max_true_peak:.1f}",
                },
            )

            clipping_known = clipped_samples is not None and clipped_samples >= 0
            clipping_ok = clipping_known and clipped_samples == 0
            if not clipping_known:
                clipping_message = "FFmpeg did not return a clipping sample count; inspect the audio manually."
            elif clipping_ok:
                clipping_message = "No clipped audio samples were reported by FFmpeg."
            else:
                clipping_message = "Clipped audio samples were detected; adjust levels and listen back."
            add(
                "audio_clipping", "Clipping scan", bool(clipping_ok),
                clipping_message,
                {"clipped_samples": clipped_samples},
                {"clipped_samples": 0},
            )

    warnings = [check["id"] for check in checks if check["status"] == "warning"]
    return {
        "status": "ready_for_operator_review" if not warnings else "review_required",
        "passed_count": sum(check["status"] == "passed" for check in checks),
        "warning_count": len(warnings),
        "checks": checks,
        "automatic_publish_approval": False,
    }
