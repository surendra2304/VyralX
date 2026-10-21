"""Studio-grade audio mixing engine with automatic voiceover ducking and loudness normalization."""
from __future__ import annotations

import logging
import math
import subprocess
from pathlib import Path

from app.config import get_settings

log = logging.getLogger("vyralx.audio_mixer")


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
    # sidechaincompress: attacks fast (20ms) when voice appears, releases smoothly (350ms)
    # threshold=-25dB, ratio=4:1, makeup=0
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
