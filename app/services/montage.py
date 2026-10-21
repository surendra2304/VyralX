"""Multi-scene FFmpeg montage renderer."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.config import get_settings
from app.services.renderer import (
    PRESETS,
    _posix_resource_limiter,
    _subtitle_filter,
    _verify_disk_space,
)


def render_montage(
    source_paths: list[str | Path],
    destination: str | Path,
    preset: str,
    *,
    target_seconds: int,
    fit_mode: str = "pad",
    subtitle_file: str | Path | None = None,
    voiceover_path: str | Path | None = None,
    bgm_path: str | Path | None = None,
    bgm_volume: float | None = None,
    ducking_attenuation_db: float | None = None,
    cpu_threads: int | None = None,
    max_memory_mb: int | None = None,
    normalize_loudness: bool = False,
    loudness_target_lufs: float = -14.0,
    enable_ken_burns: bool = False,
    motion_effects: list[str] | None = None,
) -> str:
    """Render licensed/owned clips into one silent-or-narrated montage.

    Background clip audio is discarded by design. Narration is the only audio
    source, avoiding accidental reuse of unknown third-party music or speech.
    """
    settings = get_settings()
    if not 2 <= len(source_paths) <= 8:
        raise ValueError("Montage requires 2–8 scene clips")
    if preset not in PRESETS:
        raise ValueError("Unknown render preset")
    if fit_mode not in {"pad", "crop"}:
        raise ValueError("fit_mode must be pad or crop")
    if not 15 <= int(target_seconds) <= settings.max_render_seconds:
        raise ValueError("Montage duration is outside the configured limit")

    threads = int(cpu_threads if cpu_threads is not None else getattr(settings, "render_max_cpu_threads", 1))
    threads = max(1, min(threads, 8))
    memory_mb = int(max_memory_mb if max_memory_mb is not None else getattr(settings, "render_max_memory_mb", 512))
    memory_mb = max(64, memory_mb)

    media_root = settings.media_dir.resolve()
    sources: list[Path] = []
    for raw in source_paths:
        path = Path(raw).resolve()
        if media_root not in path.parents or not path.is_file():
            raise ValueError("Every montage clip must exist inside VyralX media storage")
        sources.append(path)

    output_root = settings.render_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output = Path(destination).resolve()
    if output_root not in output.parents:
        raise ValueError("Montage output must be inside VyralX render storage")
    output.parent.mkdir(parents=True, exist_ok=True)
    _verify_disk_space(output)

    voice: Path | None = None
    if voiceover_path is not None:
        voice = Path(voiceover_path).resolve()
        if media_root not in voice.parents or not voice.is_file():
            raise ValueError("Voiceover must exist inside VyralX media storage")

    if bgm_path is not None:
        bgm = Path(bgm_path).resolve()
        if media_root not in bgm.parents or not bgm.is_file():
            raise ValueError("Background music must exist inside VyralX media storage")
        if voice is not None:
            from app.services.audio_mixer import mix_voiceover_and_bgm

            mix_dir = settings.data_dir / "audio_mix"
            mix_dir.mkdir(parents=True, exist_ok=True)
            mixed_audio = mix_dir / f"montage-mix-{output.stem}.m4a"
            mix_voiceover_and_bgm(
                voice,
                bgm,
                mixed_audio,
                target_duration=float(target_seconds),
                bgm_volume=bgm_volume,
                ducking_attenuation_db=ducking_attenuation_db,
                normalize_loudness=normalize_loudness,
                loudness_target_lufs=loudness_target_lufs,
                cpu_threads=threads,
            )
            voice = mixed_audio
        else:
            voice = bgm

    width, height = PRESETS[preset]
    segment_seconds = float(target_seconds) / len(sources)
    command = [settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y", "-threads", str(threads)]
    for source in sources:
        # Loop short stock clips so every scene fills its assigned time slice.
        command.extend(["-stream_loop", "-1", "-i", str(source)])
    audio_index = len(sources)
    if voice is not None:
        command.extend(["-i", str(voice)])

    filters: list[str] = []
    labels: list[str] = []
    for index in range(len(sources)):
        label = f"scene{index}"
        if fit_mode == "crop":
            framing = (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}:(in_w-out_w)/2:(in_h-out_h)/2"
            )
        else:
            framing = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
            )
        if enable_ken_burns:
            from app.services.visual_motion import assign_scene_motions, build_motion_filter

            motions = motion_effects or assign_scene_motions(len(sources))
            motion_type = motions[index % len(motions)]
            motion_filter = build_motion_filter(
                motion_type, width, height, duration_frames=max(30, int(segment_seconds * 30)), fps=30
            )
            filters.append(
                f"[{index}:v:0]fps=30,trim=duration={segment_seconds:.4f},"
                f"setpts=PTS-STARTPTS,{framing},{motion_filter},setsar=1[{label}]"
            )
        else:
            filters.append(
                f"[{index}:v:0]fps=30,trim=duration={segment_seconds:.4f},"
                f"setpts=PTS-STARTPTS,{framing},setsar=1[{label}]"
            )
        labels.append(f"[{label}]")
    filters.append(
        "".join(labels) + f"concat=n={len(sources)}:v=1:a=0[joined]"
    )
    if subtitle_file is not None:
        filters.append(f"[joined]{_subtitle_filter(subtitle_file, settings.data_dir)}[outv]")
    else:
        filters.append("[joined]null[outv]")
    command.extend(["-filter_complex", ";".join(filters), "-map", "[outv]"])

    audio_filters: list[str] = []
    if normalize_loudness:
        target = float(loudness_target_lufs)
        audio_filters.append(f"loudnorm=I={target:.1f}:LRA=11:TP=-1.5")
    audio_filters.append("apad")
    af_chain = ",".join(audio_filters)

    if voice is not None:
        command.extend(["-map", f"{audio_index}:a:0", "-af", af_chain, "-c:a", "aac", "-b:a", "128k"])
    else:
        command.append("-an")
    command.extend([
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-t", str(int(target_seconds)), "-threads", str(threads), str(output),
    ])

    preexec = _posix_resource_limiter(memory_mb) if os.name == "posix" else None

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=settings.max_render_seconds,
            check=False,
            preexec_fn=preexec,
        )
    except subprocess.TimeoutExpired as exc:
        output.unlink(missing_ok=True)
        raise RuntimeError("Montage render exceeded configured time limit") from exc
    except Exception:
        output.unlink(missing_ok=True)
        raise

    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        raise RuntimeError((result.stderr or "FFmpeg montage failed")[-3000:])
    return str(output)
