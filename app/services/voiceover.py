"""Voiceover providers: local eSpeak for zero-key operation, or external TTS."""
from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path
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

    if provider == "elevenlabs":
        api_key = settings.elevenlabs_api_key.strip()
        if not api_key:
            raise RuntimeError("TTS_PROVIDER=elevenlabs requires ELEVENLABS_API_KEY")
        voice_id = settings.elevenlabs_voice_id.strip() or "21m00Tcm4TlvDq8ikWAM"
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        payload = {
            "text": normalized,
            "model_id": settings.elevenlabs_model_id or "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }
        try:
            response = httpx.post(
                url,
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json=payload,
                timeout=settings.elevenlabs_timeout_seconds,
                follow_redirects=False,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"ElevenLabs TTS returned HTTP {exc.response.status_code}") from None
        except httpx.RequestError as exc:
            raise RuntimeError(f"ElevenLabs TTS request failed ({type(exc).__name__})") from None

        if not response.content or len(response.content) > 50 * 1024 * 1024:
            raise RuntimeError("ElevenLabs TTS returned empty or oversized audio")
        return _store_audio(response.content, ".mp3")

    if provider != "external":
        raise ValueError("TTS_PROVIDER must be 'espeak', 'external', or 'elevenlabs'")
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



def synthesize_voiceover_with_captions(
    text: str,
    *,
    target_seconds: int,
    max_chars: int = 100,
) -> dict[str, object]:
    """Synthesize eSpeak narration in caption-sized chunks and return measured cue times.

    Segment-wise WAV durations produce phrase/chunk-level timing, not phoneme-level
    forced alignment. External providers should use their own trusted alignment data
    or keep the captions explicitly marked as estimated.
    """
    settings = get_settings()
    normalized = " ".join(text.split())
    if settings.tts_provider.strip().lower() != "espeak":
        raise ValueError("Measured chunk captions are only supported by the local eSpeak provider")
    if not normalized:
        raise ValueError("Voiceover text must not be empty")
    if len(normalized) > 20_000:
        raise ValueError("Voiceover text exceeds the 20000-character limit")
    if target_seconds <= 0:
        raise ValueError("target_seconds must be positive")

    from app.services.captions import segment_script

    drafts = segment_script(normalized, target_seconds, max_chars=max_chars)
    if not drafts:
        raise ValueError("Caption segmentation produced no narration chunks")
    if len(drafts) > 240:
        raise ValueError("Narration requires too many separate synthesis chunks")

    executable = shutil.which(settings.espeak_bin)
    if not executable:
        raise RuntimeError(
            f"Local TTS provider is eSpeak but '{settings.espeak_bin}' is not installed"
        )

    audio_dir = settings.media_dir / "voiceovers"
    audio_dir.mkdir(parents=True, exist_ok=True)
    root = audio_dir.resolve()
    output_path = (audio_dir / (uuid4().hex + ".wav")).resolve()
    if root not in output_path.parents:
        raise RuntimeError("Invalid voiceover destination path")

    initial_rate = round(len(normalized.split()) * 60 / target_seconds)
    initial_rate = max(80, min(initial_rate, 300))
    segment_paths: list[Path] = []

    def synthesize_chunks(
        selected_rate: int,
    ) -> tuple[
        list[Path],
        list[bytes],
        list[dict[str, float | str]],
        tuple[int, int, int, str, str],
        float,
    ]:
        paths: list[Path] = []
        frame_payloads: list[bytes] = []
        caption_segments: list[dict[str, float | str]] = []
        common_format: tuple[int, int, int, str, str] | None = None
        cursor = 0.0
        total_audio_bytes = 0
        try:
            for draft in drafts:
                chunk_text = str(draft.get("text") or "").strip()
                if not chunk_text:
                    continue
                segment_path = (audio_dir / (uuid4().hex + ".wav")).resolve()
                if root not in segment_path.parents:
                    raise RuntimeError("Invalid voiceover segment destination path")
                paths.append(segment_path)
                command = [
                    executable,
                    "-w",
                    str(segment_path),
                    "-v",
                    settings.espeak_voice,
                    "-s",
                    str(selected_rate),
                    chunk_text,
                ]
                try:
                    result = subprocess.run(
                        command, capture_output=True, text=True, timeout=30, check=False
                    )
                except subprocess.TimeoutExpired:
                    raise RuntimeError("Local voiceover chunk synthesis exceeded 30 seconds") from None
                if (
                    result.returncode != 0
                    or not segment_path.is_file()
                    or segment_path.stat().st_size <= 44
                ):
                    raise RuntimeError("Local voiceover chunk synthesis failed")

                try:
                    with wave.open(str(segment_path), "rb") as audio:
                        sample_format = (
                            audio.getnchannels(),
                            audio.getsampwidth(),
                            audio.getframerate(),
                            audio.getcomptype(),
                            audio.getcompname(),
                        )
                        frames_count = audio.getnframes()
                        frame_data = audio.readframes(frames_count)
                except (OSError, EOFError, wave.Error):
                    raise RuntimeError("eSpeak returned invalid WAV audio for a caption chunk") from None

                if (
                    frames_count <= 0
                    or sample_format[2] <= 0
                    or sample_format[3] != "NONE"
                    or len(frame_data) == 0
                ):
                    raise RuntimeError("eSpeak returned empty or unsupported WAV audio")
                if common_format is None:
                    common_format = sample_format
                elif sample_format != common_format:
                    raise RuntimeError("eSpeak returned inconsistent WAV formats across caption chunks")

                total_audio_bytes += len(frame_data)
                if total_audio_bytes > 50 * 1024 * 1024:
                    raise RuntimeError("Segmented voiceover exceeds the 50 MiB audio limit")
                duration = frames_count / sample_format[2]
                start = cursor
                cursor += duration
                caption_segments.append({
                    "start_seconds": round(start, 3),
                    "end_seconds": round(cursor, 3),
                    "text": chunk_text,
                })
                frame_payloads.append(frame_data)

            if not frame_payloads or common_format is None:
                raise RuntimeError("Local voiceover synthesis produced no usable audio chunks")
            return paths, frame_payloads, caption_segments, common_format, cursor
        except Exception:
            for path in paths:
                path.unlink(missing_ok=True)
            raise

    try:
        segment_paths, frame_payloads, caption_segments, common_format, cursor = synthesize_chunks(
            initial_rate
        )
        # Chunk-level synthesis adds natural pauses that a single long TTS call does
        # not. If the first measured pass drifts from the target, adjust rate once and
        # regenerate, retaining the per-chunk measured cue boundaries.
        if abs(cursor - target_seconds) > 0.5:
            adjusted_rate = max(80, min(round(initial_rate * cursor / target_seconds), 300))
            if adjusted_rate != initial_rate:
                for path in segment_paths:
                    path.unlink(missing_ok=True)
                segment_paths, frame_payloads, caption_segments, common_format, cursor = (
                    synthesize_chunks(adjusted_rate)
                )

        channels, sample_width, sample_rate, _, _ = common_format
        try:
            with wave.open(str(output_path), "wb") as combined:
                combined.setnchannels(channels)
                combined.setsampwidth(sample_width)
                combined.setframerate(sample_rate)
                combined.setcomptype("NONE", "not compressed")
                combined.writeframes(b"".join(frame_payloads))
        except (OSError, wave.Error):
            raise RuntimeError("Could not combine measured narration chunks") from None

        if not output_path.is_file() or output_path.stat().st_size <= 44:
            raise RuntimeError("Combined voiceover output is missing or empty")
        try:
            output_path.chmod(0o600)
        except OSError:
            pass
        return {
            "file_path": str(output_path),
            "bytes": output_path.stat().st_size,
            "content_type": "audio/wav",
            "caption_segments": caption_segments,
            "caption_alignment_status": "measured_chunk",
        }
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        for segment_path in segment_paths:
            segment_path.unlink(missing_ok=True)
