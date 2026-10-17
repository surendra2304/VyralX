import subprocess
from pathlib import Path

from app.config import get_settings


PRESETS = {
    "shorts": (1080, 1920),
    "long": (1920, 1080),
    "square": (1080, 1080),
}


def render_video(source: str | Path, destination: str | Path, preset: str) -> str:
    settings = get_settings()
    src = Path(source).resolve()
    out = Path(destination).resolve()
    if not src.is_file():
        raise FileNotFoundError("Source media not found")
    if preset not in PRESETS:
        raise ValueError("Unknown render preset")
    width, height = PRESETS[preset]
    settings.render_dir.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Scale to fit and pad; preserve full image instead of silently cropping content.
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1")
    command = [
        settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y", "-i", str(src),
        "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=settings.max_render_seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Render exceeded configured time limit") from exc
    if result.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError((result.stderr or "FFmpeg failed")[-3000:])
    return str(out)
