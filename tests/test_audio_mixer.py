"""Tests for studio audio mixer with dynamic voiceover ducking."""
from unittest.mock import MagicMock, patch

import pytest

from app.services.audio_mixer import build_ducking_filter_graph, mix_voiceover_and_bgm


def test_build_ducking_filter_graph_structure():
    graph = build_ducking_filter_graph(
        voice_index=0,
        bgm_index=1,
        bgm_volume=0.25,
        ducking_attenuation_db=-18.0,
        normalize_loudness=True,
        loudness_target_lufs=-14.0,
    )
    assert "[1:a]volume=0.25[bgm_vol]" in graph
    assert "[0:a]asplit=2[voice_main][voice_sidechain]" in graph
    assert "sidechaincompress=" in graph
    assert "amix=inputs=2:duration=first" in graph
    assert "loudnorm=I=-14.0" in graph
    assert "[out_a]" in graph


def test_build_ducking_filter_graph_without_loudness():
    graph = build_ducking_filter_graph(
        voice_index=0,
        bgm_index=1,
        bgm_volume=0.15,
        ducking_attenuation_db=-12.0,
        normalize_loudness=False,
    )
    assert "loudnorm" not in graph
    assert "[mixed]anull[out_a]" in graph


def test_mix_voiceover_and_bgm_missing_files(tmp_path):
    voice = tmp_path / "voice.wav"
    bgm = tmp_path / "bgm.mp3"
    out = tmp_path / "out.m4a"

    with pytest.raises(FileNotFoundError, match="Voiceover audio file not found"):
        mix_voiceover_and_bgm(voice, bgm, out)

    voice.write_text("dummy voice", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="Background music file not found"):
        mix_voiceover_and_bgm(voice, bgm, out)


def test_mix_voiceover_and_bgm_success(tmp_path):
    voice = tmp_path / "voice.wav"
    bgm = tmp_path / "bgm.mp3"
    out = tmp_path / "out.m4a"
    voice.write_bytes(b"dummy voice content")
    bgm.write_bytes(b"dummy bgm content")

    def fake_run(cmd, stdout=None, stderr=None, text=True):
        out.write_bytes(b"rendered audio stream content")
        return MagicMock(returncode=0, stderr="")

    with patch("subprocess.run", side_effect=fake_run) as mock_run:
        result = mix_voiceover_and_bgm(
            voice,
            bgm,
            out,
            target_duration=30.0,
            bgm_volume=0.30,
            normalize_loudness=True,
            loudness_target_lufs=-14.0,
            cpu_threads=2,
        )
        assert result == str(out.resolve())
        assert out.is_file()
        assert mock_run.called
        call_args = mock_run.call_args[0][0]
        assert "-threads" in call_args
        assert "2" in call_args
        assert "-t" in call_args
        assert "30.0" in call_args


def test_mix_voiceover_and_bgm_shortest_mode(tmp_path):
    voice = tmp_path / "voice.wav"
    bgm = tmp_path / "bgm.mp3"
    out = tmp_path / "out.m4a"
    voice.write_bytes(b"dummy voice content")
    bgm.write_bytes(b"dummy bgm content")

    def fake_run(cmd, stdout=None, stderr=None, text=True):
        out.write_bytes(b"rendered audio stream content")
        return MagicMock(returncode=0, stderr="")

    with patch("subprocess.run", side_effect=fake_run) as mock_run:
        result = mix_voiceover_and_bgm(voice, bgm, out, target_duration=None)
        assert result == str(out.resolve())
        call_args = mock_run.call_args[0][0]
        assert "-shortest" in call_args
        assert "-t" not in call_args


def test_mix_voiceover_and_bgm_failure(tmp_path):
    voice = tmp_path / "voice.wav"
    bgm = tmp_path / "bgm.mp3"
    out = tmp_path / "out.m4a"
    voice.write_bytes(b"dummy voice")
    bgm.write_bytes(b"dummy bgm")

    with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="filter error")):
        with pytest.raises(RuntimeError, match="Audio ducking mix failed"):
            mix_voiceover_and_bgm(voice, bgm, out)


def test_mix_voiceover_and_bgm_empty_output(tmp_path):
    voice = tmp_path / "voice.wav"
    bgm = tmp_path / "bgm.mp3"
    out = tmp_path / "out.m4a"
    voice.write_bytes(b"dummy voice")
    bgm.write_bytes(b"dummy bgm")

    with patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")):
        with pytest.raises(RuntimeError, match="output file is empty or missing"):
            mix_voiceover_and_bgm(voice, bgm, out)
