from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from app.config import get_settings


logger = logging.getLogger("vyralx.renderer")

PRESETS = {
    "shorts": (1080, 1920),
    "long": (1920, 1080),
    "square": (1080, 1080),
}

MIN_REQUIRED_DISK_BYTES = 50 * 1024 * 1024  # 50 MB minimum headroom


def _posix_resource_limiter(max_memory_mb: int, nice_val: int = 10):
    """Return preexec_fn setting address-space limit and CPU niceness on POSIX systems."""
    def limiter():
        try:
            import resource
            if max_memory_mb > 0:
                bytes_limit = max_memory_mb * 1024 * 1024
                # Address-space (virtual memory) limit
                resource.setrlimit(resource.RLIMIT_AS, (bytes_limit, bytes_limit))
        except (ImportError, ValueError, OSError):
            pass
        try:
            os.nice(nice_val)
        except (AttributeError, OSError):
            pass
    return limiter


def _verify_disk_space(destination: Path) -> None:
    """Ensure the target filesystem has sufficient space before spawning renderers."""
    try:
        usage = shutil.disk_usage(destination.parent)
        free = getattr(usage, "free", usage[2] if isinstance(usage, tuple) and len(usage) > 2 else 0)
        if free < MIN_REQUIRED_DISK_BYTES:
            raise RuntimeError(
                f"Insufficient disk space for render: {free // (1024 * 1024)}MB free, "
                f"required at least {MIN_REQUIRED_DISK_BYTES // (1024 * 1024)}MB"
            )
    except (OSError, AttributeError):
        pass


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
    cpu_threads: int | None = None,
    max_memory_mb: int | None = None,
    normalize_loudness: bool = False,
    loudness_target_lufs: float = -14.0,
) -> str:
    """Render video with strict CPU and RAM resource bounding and quality presets."""
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

    threads = int(cpu_threads if cpu_threads is not None else getattr(settings, "render_max_cpu_threads", 1))
    threads = max(1, min(threads, 8))
    memory_mb = int(max_memory_mb if max_memory_mb is not None else getattr(settings, "render_max_memory_mb", 512))
    memory_mb = max(64, memory_mb)

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
    _verify_disk_space(out)

    command = [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-threads",
        str(threads),
    ]
    if trim_start_seconds:
        command.extend(["-ss", str(float(trim_start_seconds))])
    command.extend(["-i", str(src)])
    if voice_path is not None:
        command.extend(["-i", str(voice_path)])
    if trim_end_seconds is not None:
        command.extend(["-t", str(float(trim_end_seconds - trim_start_seconds))])
    command.extend(["-vf", filter_graph, "-map", "0:v:0"])

    audio_filters: list[str] = []
    if normalize_loudness:
        target = float(loudness_target_lufs)
        audio_filters.append(f"loudnorm=I={target:.1f}:LRA=11:TP=-1.5")
    audio_filters.append("apad")
    af_chain = ",".join(audio_filters)

    if voice_path is not None:
        command.extend(["-map", "1:a:0", "-af", af_chain, "-shortest"])
    else:
        if normalize_loudness:
            command.extend(["-map", "0:a?", "-af", f"loudnorm=I={loudness_target_lufs:.1f}:LRA=11:TP=-1.5"])
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
        out.unlink(missing_ok=True)
        raise RuntimeError("Render exceeded configured time limit") from exc
    except Exception:
        out.unlink(missing_ok=True)
        raise

    if result.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        raise RuntimeError((result.stderr or "FFmpeg failed")[-3000:])
    return str(out)


def render_video_with_moviepy(
    source: str | Path,
    destination: str | Path,
    preset: str,
    *,
    trim_start_seconds: float = 0,
    trim_end_seconds: float | None = None,
    fit_mode: str = "pad",
    voiceover_path: str | Path | None = None,
    cpu_threads: int | None = None,
    max_memory_mb: int | None = None,
    normalize_loudness: bool = False,
) -> str:
    """Render video using MoviePy when available with resource constraints, falling back to FFmpeg."""
    try:
        # Check if MoviePy is available
        import moviepy.editor as mp  # type: ignore
    except ImportError:
        # Fall back to high-performance direct FFmpeg engine
        return render_video(
            source,
            destination,
            preset,
            trim_start_seconds=trim_start_seconds,
            trim_end_seconds=trim_end_seconds,
            fit_mode=fit_mode,
            voiceover_path=voiceover_path,
            cpu_threads=cpu_threads,
            max_memory_mb=max_memory_mb,
            normalize_loudness=normalize_loudness,
        )

    settings = get_settings()
    src = Path(source).resolve()
    out = Path(destination).resolve()
    if not src.is_file():
        raise FileNotFoundError("Source media not found")
    if preset not in PRESETS:
        raise ValueError("Unknown render preset")
    target_width, target_height = PRESETS[preset]
    threads = int(cpu_threads if cpu_threads is not None else getattr(settings, "render_max_cpu_threads", 1))

    clip = None
    final_clip = None
    voice_clip = None
    try:
        clip = mp.VideoFileClip(str(src))
        if trim_start_seconds or trim_end_seconds:
            end = trim_end_seconds if trim_end_seconds is not None else clip.duration
            clip = clip.subclip(trim_start_seconds, end)

        if fit_mode == "crop":
            resized = clip.resize(height=target_height)
            if resized.w < target_width:
                resized = clip.resize(width=target_width)
            final_clip = resized.crop(
                x_center=resized.w / 2, y_center=resized.h / 2, width=target_width, height=target_height
            )
        else:
            resized = clip.resize(height=target_height)
            if resized.w > target_width:
                resized = clip.resize(width=target_width)
            final_clip = resized.margin(
                left=(target_width - resized.w) // 2,
                right=(target_width - resized.w) - (target_width - resized.w) // 2,
                top=(target_height - resized.h) // 2,
                bottom=(target_height - resized.h) - (target_height - resized.h) // 2,
                color=(0, 0, 0),
            )

        if voiceover_path:
            voice_clip = mp.AudioFileClip(str(Path(voiceover_path).resolve()))
            final_clip = final_clip.set_audio(voice_clip)

        out.parent.mkdir(parents=True, exist_ok=True)
        final_clip.write_videofile(
            str(out),
            codec="libx264",
            audio_codec="aac",
            fps=30,
            threads=threads,
            preset="veryfast",
            logger=None,
        )
        return str(out)
    finally:
        if voice_clip:
            voice_clip.close()
        if final_clip:
            final_clip.close()
        if clip:
            clip.close()
