"""Tests for ElevenLabs voiceover provider integration."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from app.config import Settings
from app.services.voiceover import synthesize_voiceover


def test_elevenlabs_config_validation():
    # Valid provider
    settings = Settings(tts_provider="elevenlabs", elevenlabs_api_key="sk_test")
    assert settings.tts_provider == "elevenlabs"
    assert settings.elevenlabs_api_key == "sk_test"

    # Invalid provider
    with pytest.raises(ValueError, match="TTS_PROVIDER must be espeak, external, or elevenlabs"):
        Settings(tts_provider="unsupported_provider")


def test_elevenlabs_synthesis_requires_api_key(monkeypatch: pytest.MonkeyPatch):
    settings = SimpleNamespace(
        tts_provider="elevenlabs",
        elevenlabs_api_key="",
        elevenlabs_voice_id="21m00Tcm4TlvDq8ikWAM",
        elevenlabs_model_id="eleven_multilingual_v2",
        elevenlabs_timeout_seconds=120,
    )
    monkeypatch.setattr("app.services.voiceover.get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="TTS_PROVIDER=elevenlabs requires ELEVENLABS_API_KEY"):
        synthesize_voiceover("Test script voiceover.")


def test_elevenlabs_synthesis_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    settings = SimpleNamespace(
        tts_provider="elevenlabs",
        elevenlabs_api_key="sk_valid_key_123",
        elevenlabs_voice_id="21m00Tcm4TlvDq8ikWAM",
        elevenlabs_model_id="eleven_multilingual_v2",
        elevenlabs_timeout_seconds=120,
        media_dir=media_dir,
    )
    monkeypatch.setattr("app.services.voiceover.get_settings", lambda: settings)

    captured_requests = []

    def mock_post(url, headers=None, json=None, timeout=None, follow_redirects=False):
        captured_requests.append({"url": url, "headers": headers, "json": json})
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.content = b"fake-elevenlabs-mp3-audio-bytes"
        response.headers = {"content-type": "audio/mpeg"}
        response.raise_for_status = lambda: None
        return response

    monkeypatch.setattr("httpx.post", mock_post)

    result = synthesize_voiceover("This is a synthesized test sentence from ElevenLabs.")
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM" in req["url"]
    assert req["headers"]["xi-api-key"] == "sk_valid_key_123"
    assert req["json"]["text"] == "This is a synthesized test sentence from ElevenLabs."

    assert result["content_type"] == "audio/mpeg"
    assert result["bytes"] == len(b"fake-elevenlabs-mp3-audio-bytes")
    assert Path(result["file_path"]).is_file()
