"""Tests for the optional HTTP word-level forced-alignment client."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services import forced_alignment


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        caption_alignment_url="http://aligner.internal:9000",
        caption_alignment_api_key="test-secret",
        caption_alignment_path="/v1/align",
        caption_alignment_timeout_seconds=45,
        caption_alignment_language="en",
    )


def _records():
    return [
        {"word": "Solar", "start": 0.18, "end": 0.30},
        {"word": "panels", "start": 0.31, "end": 0.60},
        {"word": "work.", "start": 0.61, "end": 0.80},
        {"word": "Clean", "start": 1.10, "end": 1.30},
        {"word": "power", "start": 1.31, "end": 1.60},
        {"word": "helps.", "start": 1.61, "end": 1.90},
    ]


class _Response:
    def __init__(self, payload):
        self.payload = payload
        self.content = json.dumps(payload).encode("utf-8")

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_forced_alignment_uploads_audio_and_returns_transcript_preserving_cues(tmp_path, monkeypatch):
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"fake wav data")
    monkeypatch.setattr(forced_alignment, "get_settings", _settings)
    received = {}

    def fake_post(url, **kwargs):
        received["url"] = url
        received.update(kwargs)
        return _Response({"words": _records()})

    monkeypatch.setattr(forced_alignment.httpx, "post", fake_post)
    cues = forced_alignment.align_word_timestamps(
        audio,
        "Solar panels work. Clean power helps.",
        duration_seconds=2.2,
        max_chars=100,
    )

    assert received["url"] == "http://aligner.internal:9000/v1/align"
    assert received["headers"]["Authorization"] == "Bearer test-secret"
    assert received["headers"]["X-API-Key"] == "test-secret"
    assert received["data"] == {"text": "Solar panels work. Clean power helps.", "language": "en"}
    assert received["files"]["audio_file"][0] == "voice.wav"
    assert received["timeout"] == 45
    assert cues == [
        {"start_seconds": 0.18, "end_seconds": 0.8, "text": "Solar panels work."},
        {"start_seconds": 1.1, "end_seconds": 1.9, "text": "Clean power helps."},
    ]


def test_forced_alignment_accepts_nested_word_records(tmp_path, monkeypatch):
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"fake mp3 data")
    monkeypatch.setattr(forced_alignment, "get_settings", _settings)
    records = _records()

    def fake_post(_url, **_kwargs):
        return _Response({
            "segments": [
                {"words": records[:3]},
                {"words": records[3:]},
            ]
        })

    monkeypatch.setattr(forced_alignment.httpx, "post", fake_post)
    result = forced_alignment.align_word_timestamps(
        audio, "Solar panels work. Clean power helps.", duration_seconds=2.2
    )
    assert len(result) == 2


def test_forced_alignment_rejects_word_mismatch(tmp_path, monkeypatch):
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(forced_alignment, "get_settings", _settings)

    def fake_post(_url, **_kwargs):
        return _Response({"words": [{**row} for row in _records()]})

    monkeypatch.setattr(forced_alignment.httpx, "post", fake_post)
    with pytest.raises(forced_alignment.ForcedAlignmentError, match="word sequence"):
        forced_alignment.align_word_timestamps(
            audio, "Solar panels differ. Clean power helps.", duration_seconds=2.2
        )


def test_forced_alignment_rejects_overlapping_or_out_of_bounds_timestamps(tmp_path, monkeypatch):
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(forced_alignment, "get_settings", _settings)
    invalid = _records()
    invalid[1] = {**invalid[1], "start": 0.25}

    monkeypatch.setattr(
        forced_alignment.httpx,
        "post",
        lambda *_args, **_kwargs: _Response({"words": invalid}),
    )
    with pytest.raises(forced_alignment.ForcedAlignmentError, match="timestamps"):
        forced_alignment.align_word_timestamps(
            audio, "Solar panels work. Clean power helps.", duration_seconds=2.2
        )


def test_forced_alignment_requires_url_and_api_key(tmp_path, monkeypatch):
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(
        forced_alignment,
        "get_settings",
        lambda: SimpleNamespace(caption_alignment_url="", caption_alignment_api_key=""),
    )
    with pytest.raises(forced_alignment.ForcedAlignmentError, match="CAPTION_ALIGNMENT_URL"):
        forced_alignment.align_word_timestamps(
            audio, "Solar panels work.", duration_seconds=2.0
        )


def test_settings_require_api_key_for_remote_alignment_and_valid_timeout():
    with pytest.raises(ValidationError, match="CAPTION_ALIGNMENT_API_KEY"):
        Settings(
            _env_file=None,
            caption_alignment_url="http://aligner.internal:9000",
            caption_alignment_api_key="",
        )
    with pytest.raises(ValidationError, match="CAPTION_ALIGNMENT_TIMEOUT_SECONDS"):
        Settings(_env_file=None, caption_alignment_timeout_seconds=301)
