"""Studio-grade audio mixing engine with automatic voiceover ducking, mood matching, and ambient pad synthesis."""
from __future__ import annotations

import logging
import math
import subprocess
from pathlib import Path

from app.config import get_settings

log = logging.getLogger("vyralx.audio_mixer")

TONE_MOOD_MAP = {
    "energetic": "high_energy",
    "upbeat": "high_energy",
    "fast": "high_energy",
    "mysterious": "suspense_mystery",
    "curious": "suspense_mystery",
    "dark": "suspense_mystery",
    "inspirational": "uplifting_cinematic",
    "epic": "uplifting_cinematic",
    "dramatic": "uplifting_cinematic",
    "calm": "ambient_explainer",
    "factual": "ambient_explainer",
    "clear, energetic and factual": "ambient_explainer",
    "educational": "ambient_explainer",
    "tech": "cyber_futuristic",
    "futuristic": "cyber_futuristic",
}

MOOD_SYNTH_CONFIGS = {
    "high_energy": {
        "frequencies": [220, 330, 440],
        "lowpass": 1800,
        "volume": 0.12,
    },
    "suspense_mystery": {
        "frequencies": [110, 165, 233],
        "lowpass": 650,
        "volume": 0.15,
    },
    "cyber_futuristic": {
        "frequencies": [130, 196, 293],
        "lowpass": 1200,
        "volume": 0.14,
    },
    "uplifting_cinematic": {
        "frequencies": [174, 261, 349],
        "lowpass": 1400,
        "volume": 0.13,
    },
    "ambient_explainer": {
        "frequencies": [220, 277, 330],
        "lowpass": 900,
        "volume": 0.12,
    },
}


def build_ducking_filter_graph(
    voice_index: int = 0,
    bgm_index: int = 1,
    bgm_volume: float = 0.20,
    ducking_attenuation_db: float = -16.0,
    *,
    normalize_loudness: bool = True,
    loudness_target_lufs: float = -14.0,
) -> str:
    """Construct an FFmpeg audio filtergraph that ducks background music under speech."""
    bgm_vol = max(0.01, min(float(bgm_volume), 1.0))
    filter_steps = [
        f"[{bgm_index}:a]volume={bgm_vol:.2f}[bgm_vol]",
        f"[{voice_index}:a]asplit=2[voice_main][voice_sidechain]",
        "[bgm_vol][voice_sidechain]sidechaincompress=threshold=0.08:ratio=5:attack=25:release=350[ducked_bgm]",
        "[voice_main][ducked_bgm]amix=inputs=2:duration=first:dropout_transition=2[mixed]",
    ]
    if normalize_loudness:
        target = float(loudness_target_lufs)
        filter_steps.append(f"[mixed]loudnorm=I={target:.1f}:LRA=9:TP=-1.5[out_a]")
    else:
        filter_steps.append("[mixed]anull[out_a]")

    return ";".join(filter_steps)


def select_bgm_track_for_tone(
    tone: str,
    music_dir: Path | str | None = None,
) -> Path | None:
    """Select appropriate BGM audio file from music library matching desired tone."""
    settings = get_settings()
    directory = Path(music_dir) if music_dir else (settings.data_dir / "music")
    if not directory.is_dir():
        return None

    clean_tone = str(tone).lower().strip()
    target_mood = TONE_MOOD_MAP.get(clean_tone, "ambient_explainer")

    # Search for audio files with mood keyword in filename
    extensions = ("*.mp3", "*.wav", "*.m4a", "*.aac", "*.ogg")
    all_files: list[Path] = []
    for ext in extensions:
        all_files.extend(directory.glob(ext))

    if not all_files:
        return None

    # Priority 1: Match target mood
    for f in all_files:
        if target_mood in f.stem.lower():
            return f

    # Priority 2: Match any token from tone
    tokens = clean_tone.split()
    for f in all_files:
        if any(tok in f.stem.lower() for tok in tokens if len(tok) >= 4):
            return f

    # Priority 3: Fall back to first audio track
    return all_files[0]


def synthesize_ambient_pad_bgm(
    output_path: str | Path,
    duration_seconds: float,
    mood: str = "ambient_explainer",
) -> Path:
    """Synthesize a smooth ambient background musical pad using FFmpeg audio synthesis."""
    settings = get_settings()
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    dur = max(1.0, float(duration_seconds))
    clean_mood = mood.lower().strip()
    cfg = MOOD_SYNTH_CONFIGS.get(clean_mood, MOOD_SYNTH_CONFIGS["ambient_explainer"])

    freqs = cfg["frequencies"]
    lp = cfg["lowpass"]
    vol = cfg["volume"]

    # Build layered harmonic sine sources
    inputs = []
    labels = []
    for idx, f in enumerate(freqs):
        inputs.extend(["-f", "lavfi", "-i", f"sine=frequency={f}:duration={dur:.2f}"])
        labels.append(f"[{idx}:a]")

    filter_complex = (
        f"{''.join(labels)}amix=inputs={len(freqs)}:duration=first[chords];"
        f"[chords]lowpass=f={lp},volume={vol:.2f},afade=t=in:ss=0:d=1.5,afade=t=out:st={max(0.1, dur - 2.0):.2f}:d=2.0[out_a]"
    )

    cmd = [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-nostdin",
        "-y",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[out_a]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(out),
    ]

    log.info("Synthesizing ambient pad audio: %s", " ".join(cmd[:10]))
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        log.warning("FFmpeg binary not found at %s; creating fallback ambient audio stream", settings.ffmpeg_bin)
        out.write_bytes(b"\xff\xf1\x50\x80" + b"\x00" * 1024)
        return out

    if result.returncode != 0:
        log.error("FFmpeg ambient audio synthesis failed: %s", result.stderr[-600:])
        raise RuntimeError(f"FFmpeg ambient audio synthesis failed: {result.stderr[-200:].strip()}")

    if not out.is_file() or out.stat().st_size <= 0:
        raise RuntimeError("Ambient pad synthesis generated empty or missing output")

    log.info("Ambient pad synthesized: %s (size=%d bytes)", out, out.stat().st_size)
    return out


def mix_voiceover_and_bgm(
    voice_path: str | Path,
    bgm_path: str | Path,
    output_path: str | Path,
    *,
    target_duration: float | None = None,
    bgm_volume: float | None = None,
    ducking_attenuation_db: float | None = None,
    normalize_loudness: bool = True,
    loudness_target_lufs: float = -14.0,
    cpu_threads: int | None = None,
) -> str:
    """Mix speech narration and background music with dynamic ducking into a master track."""
    settings = get_settings()
    voice = Path(voice_path).resolve()
    bgm = Path(bgm_path).resolve()
    out = Path(output_path).resolve()

    if not voice.is_file():
        raise FileNotFoundError(f"Voiceover audio file not found: {voice}")
    if not bgm.is_file():
        raise FileNotFoundError(f"Background music file not found: {bgm}")

    vol = float(bgm_volume if bgm_volume is not None else getattr(settings, "bgm_default_volume", 0.20))
    att_db = float(ducking_attenuation_db if ducking_attenuation_db is not None else getattr(settings, "bgm_ducking_attenuation_db", -16.0))
    threads = max(1, min(int(cpu_threads or getattr(settings, "render_max_cpu_threads", 1)), 4))

    out.parent.mkdir(parents=True, exist_ok=True)
    filter_graph = build_ducking_filter_graph(
        voice_index=0,
        bgm_index=1,
        bgm_volume=vol,
        ducking_attenuation_db=att_db,
        normalize_loudness=normalize_loudness,
        loudness_target_lufs=loudness_target_lufs,
    )

    cmd = [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-threads",
        str(threads),
        "-i",
        str(voice),
        "-stream_loop",
        "-1",
        "-i",
        str(bgm),
        "-filter_complex",
        filter_graph,
        "-map",
        "[out_a]",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
    ]
    if target_duration is not None and math.isfinite(target_duration) and target_duration > 0:
        cmd.extend(["-t", str(float(target_duration))])
    else:
        cmd.append("-shortest")

    cmd.append(str(out))
    log.info("Executing BGM ducking mix: %s", " ".join(cmd[:10]))
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        log.error("FFmpeg audio mix failed: %s", result.stderr[-800:])
        raise RuntimeError(f"Audio ducking mix failed: {result.stderr[-200:].strip()}")

    if not out.is_file() or out.stat().st_size <= 0:
        raise RuntimeError("Audio mix completed but output file is empty or missing")

    log.info("Audio mix completed successfully: %s", out)
    return str(out)
