"""Voiceover providers: local eSpeak for zero-key operation, or external TTS."""
from __future__ import annotations

import shutil
import subprocess
from uuid import uuid4

import httpx

from app.config import get_settings


def _store_audio(data: bytes, suffix: str) -> dict[str, str | int]:
    settings = get_settings()
    audio_dir = settings.media_dir / "voiceovers"
    audio_dir.mkdir(parents=True, exist_ok=True)
    path = (audio_dir / (uuid4().hex + suffix)).resolve()
    if audio_dir.resolve() not in path.parents:
        raise RuntimeError("Invalid voiceover destination path")
    path.write_bytes(data)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return {
        "file_path": str(path),
        "bytes": len(data),
        "content_type": "audio/wav" if suffix == ".wav" else "audio/mpeg",
    }


def synthesize_voiceover(text: str, *, target_seconds: int | None = None) -> dict[str, str | int]:
    """Synthesize a script locally with eSpeak or use an explicitly configured TTS API."""
    settings = get_settings()
    normalized = " ".join(text.split())
    if not normalized:
        raise ValueError("Voiceover text must not be empty")
    if len(normalized) > 20_000:
        raise ValueError("Voiceover text exceeds the 20000-character limit")
    if target_seconds is not None and target_seconds <= 0:
        raise ValueError("target_seconds must be positive")

    provider = settings.tts_provider.strip().lower()
    if provider == "espeak":
        executable = shutil.which(settings.espeak_bin)
        if not executable:
            raise RuntimeError(
                f"Local TTS provider is eSpeak but '{settings.espeak_bin}' is not installed"
            )
        audio_dir = settings.media_dir / "voiceovers"
        audio_dir.mkdir(parents=True, exist_ok=True)
        path = (audio_dir / (uuid4().hex + ".wav")).resolve()
        if audio_dir.resolve() not in path.parents:
            raise RuntimeError("Invalid voiceover destination path")
        # eSpeak uses words per minute; estimate a target-aware rate for the project duration.
        rate = settings.espeak_rate
        if target_seconds is not None:
            rate = round(len(normalized.split()) * 60 / target_seconds)
        rate = max(80, min(rate, 300))
        command = [
            executable, "-w", str(path), "-v", settings.espeak_voice,
            "-s", str(rate), normalized,
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=120, check=False
            )
        except subprocess.TimeoutExpired as exc:
            path.unlink(missing_ok=True)
            raise RuntimeError("Local voiceover synthesis exceeded 120 seconds") from exc
        if result.returncode != 0 or not path.is_file() or path.stat().st_size == 0:
            path.unlink(missing_ok=True)
            raise RuntimeError("Local voiceover synthesis failed; check eSpeak installation")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return {"file_path": str(path), "bytes": path.stat().st_size, "content_type": "audio/wav"}

    if provider != "external":
        raise ValueError("TTS_PROVIDER must be 'espeak' or 'external'")
    tts_base_url = settings.inference_tts_url.strip()
    if not tts_base_url:
        raise RuntimeError("TTS_PROVIDER=external requires INFERENCE_TTS_URL")
    api_key = settings.inference_tts_api_key or settings.inference_api_key
    if not api_key:
        raise RuntimeError("INFERENCE_TTS_API_KEY or INFERENCE_API_KEY must be configured")
    if not settings.inference_tts_model:
        raise RuntimeError("INFERENCE_TTS_MODEL must be configured for external voiceover generation")
    url = tts_base_url.rstrip("/") + settings.inference_tts_path
    try:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "X-API-Key": api_key,
                "Content-Type": "application/json",
            },
            json={
                "model": settings.inference_tts_model,
                "input": normalized,
                "voice": settings.inference_tts_voice,
                "response_format": "mp3",
            },
            timeout=settings.inference_tts_timeout_seconds,
            follow_redirects=False,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"TTS provider returned HTTP {exc.response.status_code}") from None
    except httpx.RequestError as exc:
        raise RuntimeError(f"TTS request failed ({type(exc).__name__})") from None
    content_type = response.headers.get("content-type", "").lower()
    if not response.content or len(response.content) > 50 * 1024 * 1024:
        raise RuntimeError("TTS provider returned empty or oversized audio")
    if not any(value in content_type for value in ("audio/", "application/octet-stream")):
        raise RuntimeError("TTS response is not an audio media type")
    return _store_audio(response.content, ".mp3")
