from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import voiceover


def _settings(tmp_path):
    return SimpleNamespace(
        tts_provider="espeak",
        espeak_bin="espeak-ng",
        espeak_voice="en-us",
        espeak_rate=165,
        media_dir=tmp_path / "media",
    )


def _write_test_wave(path: Path, word_count: int) -> float:
    rate = 22050
    duration = 0.18 + word_count * 0.17
    frames = round(duration * rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(bytes(frames * 2))
    return frames / rate


def test_segmented_espeak_returns_caption_cues_timed_from_actual_wav_durations(tmp_path, monkeypatch):
    monkeypatch.setattr(voiceover, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(voiceover.shutil, "which", lambda _binary: "/usr/bin/espeak-ng")
    synthesized = []

    def fake_run(command, **kwargs):
        assert kwargs["timeout"] == 30
        assert kwargs["check"] is False
        output_path = Path(command[command.index("-w") + 1])
        text = command[-1]
        duration = _write_test_wave(output_path, len(text.split()))
        synthesized.append({"text": text, "duration": duration, "path": output_path})
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(voiceover.subprocess, "run", fake_run)
    script = (
        "The first solar panel converts sunlight to electrical energy. "
        "Cells connected together generate useful direct current. "
        "An inverter changes the electricity for home appliances."
    )

    result = voiceover.synthesize_voiceover_with_captions(script, target_seconds=20)

    assert result["caption_alignment_status"] == "measured_chunk"
    cues = result["caption_segments"]
    assert isinstance(cues, list) and len(cues) == len(synthesized) >= 3
    assert " ".join(str(cue["text"]) for cue in cues) == script

    cursor = 0.0
    for cue, chunk in zip(cues, synthesized, strict=True):
        assert cue["start_seconds"] == round(cursor, 3)
        cursor += chunk["duration"]
        assert cue["end_seconds"] == round(cursor, 3)
        assert cue["text"] == chunk["text"]
    output_path = Path(str(result["file_path"]))
    assert output_path.is_file()
    assert output_path.parent == (tmp_path / "media" / "voiceovers").resolve()
    with wave.open(str(output_path), "rb") as combined:
        assert combined.getnchannels() == 1
        assert combined.getsampwidth() == 2
        assert combined.getframerate() == 22050
        assert abs(combined.getnframes() / combined.getframerate() - cursor) < 0.002

    # Only the retained combined audio remains; temporary per-caption WAVs are removed.
    assert list(output_path.parent.glob("*.wav")) == [output_path]


def test_segmented_espeak_cleans_partial_chunks_when_a_chunk_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(voiceover, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(voiceover.shutil, "which", lambda _binary: "/usr/bin/espeak-ng")
    calls = 0

    def fake_run(command, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            output_path = Path(command[command.index("-w") + 1])
            _write_test_wave(output_path, 4)
            return SimpleNamespace(returncode=0, stderr="", stdout="")
        return SimpleNamespace(returncode=1, stderr="not persisted", stdout="")

    monkeypatch.setattr(voiceover.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="chunk synthesis failed"):
        voiceover.synthesize_voiceover_with_captions(
            (
                "The first short sentence contains enough words to split into a separate caption. "
                "The second short sentence contains more words to create another caption."
            ),
            target_seconds=15,
            max_chars=40,
        )

    audio_dir = tmp_path / "media" / "voiceovers"
    assert not list(audio_dir.glob("*.wav"))


def test_segmented_caption_synthesis_fails_closed_for_external_tts(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    settings.tts_provider = "external"
    monkeypatch.setattr(voiceover, "get_settings", lambda: settings)

    with pytest.raises(ValueError, match="only supported by the local eSpeak"):
        voiceover.synthesize_voiceover_with_captions(
            "A test narration sentence.", target_seconds=15
        )
