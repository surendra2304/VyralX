"""Optional OpenAI-compatible Inference text-to-speech adapter."""
from __future__ import annotations

from uuid import uuid4

import httpx

from app.config import get_settings


def synthesize_voiceover(text: str) -> dict[str, str | int]:
    settings = get_settings()
    if not settings.inference_url or not settings.inference_api_key:
        raise RuntimeError("INFERENCE_URL and INFERENCE_API_KEY must be configured")
    if not settings.inference_tts_model:
        raise RuntimeError("INFERENCE_TTS_MODEL must be configured for voiceover generation")
    if not text.strip():
        raise ValueError("Voiceover text must not be empty")
    if len(text) > 20_000:
        raise ValueError("Voiceover text exceeds the 20000-character limit")
    url = settings.inference_url.rstrip("/") + settings.inference_tts_path
    try:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.inference_api_key}",
                "X-API-Key": settings.inference_api_key,
                "Content-Type": "application/json",
            },
            json={
                "model": settings.inference_tts_model,
                "input": text,
                "voice": settings.inference_tts_voice,
                "response_format": "mp3",
            },
            timeout=settings.inference_tts_timeout_seconds,
            follow_redirects=False,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Inference TTS returned HTTP {exc.response.status_code}") from None
    except httpx.RequestError as exc:
        raise RuntimeError(f"Inference TTS request failed ({type(exc).__name__})") from None
    content_type = response.headers.get("content-type", "").lower()
    if not response.content or len(response.content) > 50 * 1024 * 1024:
        raise RuntimeError("Inference TTS returned empty or oversized audio")
    if not any(value in content_type for value in ("audio/", "application/octet-stream")):
        raise RuntimeError("Inference TTS response is not an audio media type")
    audio_dir = settings.media_dir / "voiceovers"
    audio_dir.mkdir(parents=True, exist_ok=True)
    path = (audio_dir / (uuid4().hex + ".mp3")).resolve()
    if audio_dir.resolve() not in path.parents:
        raise RuntimeError("Invalid voiceover destination path")
    path.write_bytes(response.content)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return {"file_path": str(path), "bytes": len(response.content), "content_type": content_type}
