"""Optional HTTP-backed word-level forced alignment for generated narration.

The aligner is an independently hosted CPU/GPU service. VyralX validates its output
against the exact transcript and measured audio duration before using any timestamps.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import get_settings


class ForcedAlignmentError(RuntimeError):
    """The optional alignment service is unavailable or returned unsafe timing data."""


_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
_TERMINAL_PUNCTUATION = (".", "!", "?", ";", ":")


def _token(value: str) -> str:
    return value.casefold().replace("’", "'")


def _word_records(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ForcedAlignmentError("Alignment response must be a JSON object")
    direct = payload.get("words")
    if isinstance(direct, list):
        records = direct
    else:
        segments = payload.get("segments")
        if not isinstance(segments, list):
            raise ForcedAlignmentError("Alignment response must include word-level timestamps")
        records = []
        for segment in segments:
            if not isinstance(segment, dict):
                raise ForcedAlignmentError("Alignment response contains an invalid segment")
            nested = segment.get("words")
            if isinstance(nested, list):
                records.extend(nested)
            else:
                records.append(segment)
    if not records or any(not isinstance(record, dict) for record in records):
        raise ForcedAlignmentError("Alignment response contains no usable words")
    return records


def _request_word_records(
    audio_path: Path,
    transcript: str,
    *,
    language: str,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    settings = get_settings()
    base_url = str(getattr(settings, "caption_alignment_url", "") or "").strip().rstrip("/")
    api_key = str(getattr(settings, "caption_alignment_api_key", "") or "").strip()
    endpoint_path = str(
        getattr(settings, "caption_alignment_path", "/v1/align") or "/v1/align"
    ).strip()
    if not base_url or not api_key:
        raise ForcedAlignmentError(
            "Word-level alignment requires CAPTION_ALIGNMENT_URL and CAPTION_ALIGNMENT_API_KEY"
        )
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
        raise ForcedAlignmentError("CAPTION_ALIGNMENT_URL must be an absolute HTTP(S) base URL")
    if not endpoint_path.startswith("/") or endpoint_path.startswith("//") or "?" in endpoint_path or "#" in endpoint_path:
        raise ForcedAlignmentError("CAPTION_ALIGNMENT_PATH must be a safe absolute path")
    if not 1 <= int(timeout_seconds) <= 300:
        raise ForcedAlignmentError("Alignment timeout must be between 1 and 300 seconds")
    if not audio_path.is_file() or audio_path.stat().st_size <= 0:
        raise ForcedAlignmentError("Narration file is missing or empty")
    if audio_path.stat().st_size > 50 * 1024 * 1024:
        raise ForcedAlignmentError("Narration file exceeds the 50 MiB alignment limit")

    suffix = audio_path.suffix.lower()
    media_type = "audio/wav" if suffix == ".wav" else "audio/mpeg" if suffix == ".mp3" else "application/octet-stream"
    url = base_url + endpoint_path
    try:
        with audio_path.open("rb") as audio_handle:
            response = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "X-API-Key": api_key,
                },
                data={"text": transcript, "language": language},
                files={"audio_file": (audio_path.name, audio_handle, media_type)},
                timeout=timeout_seconds,
                follow_redirects=False,
            )
        response.raise_for_status()
    except httpx.TimeoutException:
        raise ForcedAlignmentError("Word-level alignment service timed out") from None
    except httpx.HTTPStatusError as exc:
        status_code = int(getattr(exc.response, "status_code", 0) or 0)
        raise ForcedAlignmentError(
            f"Word-level alignment service returned HTTP {status_code or 'error'}"
        ) from None
    except httpx.RequestError as exc:
        raise ForcedAlignmentError(
            f"Word-level alignment request failed ({type(exc).__name__})"
        ) from None
    if not response.content or len(response.content) > 5 * 1024 * 1024:
        raise ForcedAlignmentError("Alignment service returned an empty or oversized response")
    try:
        payload = response.json()
    except ValueError:
        raise ForcedAlignmentError("Alignment service returned invalid JSON") from None
    return _word_records(payload)


def align_word_timestamps(
    audio_path: str | Path,
    transcript: str,
    *,
    duration_seconds: float,
    max_chars: int = 100,
    language: str | None = None,
) -> list[dict[str, float | str]]:
    """Return phrase-sized captions grouped from validated word-level timestamps.

    The configured HTTP service receives multipart audio_file, text, and language
    fields. It must return words (or nested segments[].words) with each word's
    text plus start/end seconds.
    """
    normalized = " ".join(str(transcript or "").split())
    matches = list(_WORD.finditer(normalized))
    if not matches:
        raise ForcedAlignmentError("Transcript has no alignable words")
    if len(matches) > 20_000:
        raise ForcedAlignmentError("Transcript exceeds the 20000-word alignment limit")
    if max_chars < 1:
        raise ForcedAlignmentError("Maximum caption length must be positive")
    try:
        duration = float(duration_seconds)
    except (TypeError, ValueError):
        raise ForcedAlignmentError("Narration duration must be finite and positive") from None
    if not math.isfinite(duration) or duration <= 0:
        raise ForcedAlignmentError("Narration duration must be finite and positive")

    settings = get_settings()
    selected_language = (
        str(language or getattr(settings, "caption_alignment_language", "en") or "en").strip()
    )
    if not selected_language or len(selected_language) > 20 or any(ch.isspace() for ch in selected_language):
        raise ForcedAlignmentError("Alignment language must be a short language tag")
    timeout_seconds = int(getattr(settings, "caption_alignment_timeout_seconds", 90))
    records = _request_word_records(
        Path(audio_path).resolve(),
        normalized,
        language=selected_language,
        timeout_seconds=timeout_seconds,
    )
    if len(records) != len(matches):
        raise ForcedAlignmentError("Alignment word count does not match the narration transcript")

    aligned: list[dict[str, float | str]] = []
    previous_end = 0.0
    for index, (record, match) in enumerate(zip(records, matches, strict=True)):
        returned_text = str(record.get("word") or record.get("text") or record.get("token") or "").strip()
        returned_tokens = _WORD.findall(returned_text)
        if len(returned_tokens) != 1 or _token(returned_tokens[0]) != _token(match.group(0)):
            raise ForcedAlignmentError("Alignment word sequence differs from the narration transcript")
        try:
            start = float(record.get("start_seconds", record.get("start")))
            end = float(record.get("end_seconds", record.get("end")))
        except (TypeError, ValueError):
            raise ForcedAlignmentError("Alignment word has invalid start/end timestamps") from None
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end <= start
            or start < previous_end
            or end > duration + 0.15
        ):
            raise ForcedAlignmentError("Alignment word timestamps are outside valid audio bounds")
        start = round(start, 3)
        end = round(min(end, duration), 3)
        if end <= start:
            raise ForcedAlignmentError("Alignment word duration is too short for SRT timestamps")
        token_end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        word_text = normalized[match.start():token_end].strip()
        if not word_text:
            word_text = match.group(0)
        aligned.append({"start_seconds": start, "end_seconds": end, "text": word_text})
        previous_end = end

    captions: list[dict[str, float | str]] = []
    current: list[dict[str, float | str]] = []

    def flush() -> None:
        if not current:
            return
        captions.append({
            "start_seconds": float(current[0]["start_seconds"]),
            "end_seconds": float(current[-1]["end_seconds"]),
            "text": " ".join(str(item["text"]) for item in current),
        })
        current.clear()

    for word in aligned:
        proposed = " ".join([*(str(item["text"]) for item in current), str(word["text"])])
        if current and len(proposed) > max_chars:
            flush()
        current.append(word)
        if str(word["text"]).rstrip().endswith(_TERMINAL_PUNCTUATION):
            flush()
    flush()
    return captions
