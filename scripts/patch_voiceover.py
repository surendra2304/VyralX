from pathlib import Path

path = Path("app/services/voiceover.py")
content = path.read_text(encoding="utf-8")

old_snippet = """    if provider == "elevenlabs":
        api_key = settings.elevenlabs_api_key.strip()
        if not api_key:
            raise RuntimeError("TTS_PROVIDER=elevenlabs requires ELEVENLABS_API_KEY")
        voice_id = settings.elevenlabs_voice_id.strip() or "pNInz6obpgDQGcFmaJgB"
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
        return _store_audio(response.content, ".mp3")"""

new_snippet = """    if provider == "elevenlabs":
        api_key = settings.elevenlabs_api_key.strip()
        if not api_key:
            raise RuntimeError("TTS_PROVIDER=elevenlabs requires ELEVENLABS_API_KEY")
        voice_id = settings.elevenlabs_voice_id.strip() or "pNInz6obpgDQGcFmaJgB"
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
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
                    "Accept": "application/json",
                },
                json=payload,
                timeout=settings.elevenlabs_timeout_seconds,
                follow_redirects=False,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {400, 404, 422}:
                try:
                    fallback_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                    response = httpx.post(
                        fallback_url,
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
                except Exception:
                    raise RuntimeError(f"ElevenLabs TTS returned HTTP {exc.response.status_code}") from None
            else:
                raise RuntimeError(f"ElevenLabs TTS returned HTTP {exc.response.status_code}") from None
        except httpx.RequestError as exc:
            raise RuntimeError(f"ElevenLabs TTS request failed ({type(exc).__name__})") from None

        audio_bytes: bytes = b""
        cues: list[dict] | None = None
        alignment_status: str | None = None
        try:
            resp_data = response.json()
            if isinstance(resp_data, dict) and "audio_base64" in resp_data:
                import base64
                audio_bytes = base64.b64decode(resp_data["audio_base64"])
                if "alignment" in resp_data and isinstance(resp_data["alignment"], dict):
                    cues = _alignment_to_caption_cues(resp_data["alignment"])
                    if cues:
                        alignment_status = "word_forced"
        except Exception:
            audio_bytes = response.content

        if not audio_bytes:
            audio_bytes = response.content

        if not audio_bytes or len(audio_bytes) > 50 * 1024 * 1024:
            raise RuntimeError("ElevenLabs TTS returned empty or oversized audio")
        stored = _store_audio(audio_bytes, ".mp3")
        if cues:
            stored["caption_segments"] = cues
            stored["caption_alignment_status"] = alignment_status or "word_forced"
        return stored"""

content_norm = content.replace("\r\n", "\n")
old_norm = old_snippet.replace("\r\n", "\n")
assert old_norm in content_norm, "old_snippet not found in voiceover.py"
content_updated = content_norm.replace(old_norm, new_snippet.replace("\r\n", "\n"))
path.write_text(content_updated, encoding="utf-8")
print("Updated voiceover.py successfully")
