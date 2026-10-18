import subprocess
from pathlib import Path

from app.config import get_settings


PRESETS = {
    "shorts": (1080, 1920),
    "long": (1920, 1080),
    "square": (1080, 1080),
}


def _subtitle_filter(path: str | Path, data_root: Path) -> str:
    subtitle = Path(path).resolve()
    if data_root.resolve() not in subtitle.parents or not subtitle.is_file():
        raise ValueError("Subtitle file must be generated inside the VyralX data directory")
    escaped = subtitle.as_posix().replace(":", r"\:").replace("'", r"\'")
    return (
        f"subtitles='{escaped}':force_style="
        "'FontName=Arial,FontSize=24,Outline=2,Shadow=1,MarginV=80'"
    )


def render_video(
    source: str | Path,
    destination: str | Path,
    preset: str,
    *,
    trim_start_seconds: float = 0,
    trim_end_seconds: float | None = None,
    fit_mode: str = "pad",
    subtitle_file: str | Path | None = None,
    voiceover_path: str | Path | None = None,
) -> str:
    settings = get_settings()
    src = Path(source).resolve()
    out = Path(destination).resolve()
    if not src.is_file():
        raise FileNotFoundError("Source media not found")
    if preset not in PRESETS:
        raise ValueError("Unknown render preset")
    if fit_mode not in {"pad", "crop"}:
        raise ValueError("fit_mode must be pad or crop")
    if trim_start_seconds < 0:
        raise ValueError("trim_start_seconds must be non-negative")
    if trim_end_seconds is not None and trim_end_seconds <= trim_start_seconds:
        raise ValueError("trim_end_seconds must be greater than trim_start_seconds")
    width, height = PRESETS[preset]
    filters: list[str] = []
    if fit_mode == "crop":
        filters.append(
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:(in_w-out_w)/2:(in_h-out_h)/2"
        )
    else:
        filters.append(
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    filters.append("setsar=1")
    if subtitle_file is not None:
        filters.append(_subtitle_filter(subtitle_file, settings.data_dir))
    filter_graph = ",".join(filters)

    voice_path: Path | None = None
    if voiceover_path is not None:
        voice_path = Path(voiceover_path).resolve()
        if settings.media_dir.resolve() not in voice_path.parents or not voice_path.is_file():
            raise ValueError("Voiceover file must be stored in the VyralX media directory")

    settings.render_dir.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    command = [settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y", "-threads", "1"]
    if trim_start_seconds:
        command.extend(["-ss", str(float(trim_start_seconds))])
    command.extend(["-i", str(src)])
    if voice_path is not None:
        command.extend(["-i", str(voice_path)])
    if trim_end_seconds is not None:
        command.extend(["-t", str(float(trim_end_seconds - trim_start_seconds))])
    command.extend(["-vf", filter_graph, "-map", "0:v:0"])
    if voice_path is not None:
        command.extend(["-map", "1:a:0", "-af", "apad", "-shortest"])
    else:
        command.extend(["-map", "0:a?"])
    command.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(out),
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
        raise RuntimeError("Render exceeded configured time limit") from exc
    if result.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        raise RuntimeError((result.stderr or "FFmpeg failed")[-3000:])
    return str(out)
