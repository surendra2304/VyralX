from pathlib import Path

# 1. Patch voiceover.py
vp = Path("app/services/voiceover.py")
v_text = vp.read_text(encoding="utf-8")

old_def = "def synthesize_voiceover(text: str, *, target_seconds: int | None = None) -> dict[str, str | int | list | float]:"
new_def = "def synthesize_voiceover(text: str, *, target_seconds: int | None = None, voice_id: str | None = None, stability: float | None = None, style: float | None = None) -> dict[str, str | int | list | float]:"
assert old_def in v_text, "old_def not found"
v_text = v_text.replace(old_def, new_def)

old_payload = """        voice_id = settings.elevenlabs_voice_id.strip() or "pNInz6obpgDQGcFmaJgB"
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
        payload = {
            "text": normalized,
            "model_id": settings.elevenlabs_model_id or "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }"""

new_payload = """        target_voice = voice_id or settings.elevenlabs_voice_id.strip() or "JBFqnCBsd6RMkjVDRZzb"
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{target_voice}/with-timestamps"
        payload = {
            "text": normalized,
            "model_id": settings.elevenlabs_model_id or "eleven_multilingual_v2",
            "voice_settings": {
                "stability": stability if stability is not None else 0.30,
                "similarity_boost": 0.82,
                "style": style if style is not None else 0.45,
                "use_speaker_boost": True,
            },
        }"""

assert old_payload.replace("\r\n", "\n") in v_text.replace("\r\n", "\n"), "old_payload not found"
v_text = v_text.replace("\r\n", "\n").replace(old_payload.replace("\r\n", "\n"), new_payload)
vp.write_text(v_text, encoding="utf-8")
print("Updated voiceover.py with voice_id and high emotion settings")

# 2. Patch project_pipeline.py
pp = Path("app/services/project_pipeline.py")
p_text = pp.read_text(encoding="utf-8")

old_call = "                    voice = synthesize_voiceover(caption_text, target_seconds=project.target_seconds)"
new_call = """                    chosen_voice = pack.get("voice_id")
                    if not chosen_voice:
                        topic_low = project.topic.lower()
                        if any(w in topic_low for w in ("psych", "mind", "trick", "liar", "dark", "secret", "fbi")):
                            chosen_voice = "N2lVS1w4EtoT3dr4eOWO"
                        else:
                            chosen_voice = "JBFqnCBsd6RMkjVDRZzb"
                    voice = synthesize_voiceover(caption_text, target_seconds=project.target_seconds, voice_id=chosen_voice)"""

assert old_call in p_text, "old_call not found in pipeline"
p_text = p_text.replace(old_call, new_call)
pp.write_text(p_text, encoding="utf-8")
print("Updated project_pipeline.py to pass emotional voice_id")
