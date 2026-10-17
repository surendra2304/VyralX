"""Multi-scene FFmpeg montage renderer."""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.config import get_settings
from app.services.renderer import PRESETS, _subtitle_filter


def render_montage(
    source_paths: list[str | Path],
    destination: str | Path,
    preset: str,
    *,
    target_seconds: int,
    fit_mode: str = "pad",
    subtitle_file: str | Path | None = None,
    voiceover_path: str | Path | None = None,
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

    voice: Path | None = None
    if voiceover_path is not None:
        voice = Path(voiceover_path).resolve()
        if media_root not in voice.parents or not voice.is_file():
            raise ValueError("Voiceover must exist inside VyralX media storage")

    width, height = PRESETS[preset]
    segment_seconds = float(target_seconds) / len(sources)
    command = [settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y", "-threads", "1"]
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
        filters.append(
            f"[{index}:v:0]fps=30,trim=duration={segment_seconds:.4f},"
            f"setpts=PTS-STARTPTS,{framing},setsar=1[{label}]"
        )
        labels.append(f"[{label}]")
    filters.append(
        "".join(labels) + f"concat=n={len(sources)}:v=1:a=0[outv]"
    )
    command.extend(["-filter_complex", ";".join(filters), "-map", "[outv]"])
    if subtitle_file is not None:
        command.extend(["-vf", _subtitle_filter(subtitle_file, settings.data_dir)])
    if voice is not None:
        command.extend(["-map", f"{audio_index}:a:0", "-af", "apad", "-c:a", "aac", "-b:a", "128k"])
    else:
        command.append("-an")
    command.extend([
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-t", str(int(target_seconds)), "-threads", "1", str(output),
    ])
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=settings.max_render_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output.unlink(missing_ok=True)
        raise RuntimeError("Montage render exceeded configured time limit") from exc
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        raise RuntimeError((result.stderr or "FFmpeg montage failed")[-3000:])
    return str(output)
