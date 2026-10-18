import json
import subprocess
from pathlib import Path

from app.config import get_settings


def probe_media(path: str | Path) -> dict:
    file_path = Path(path).resolve()
    if not file_path.is_file():
        raise FileNotFoundError("Media file does not exist")
    settings = get_settings()
    result = subprocess.run(
        [settings.ffprobe_bin, "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height", "-of", "json", str(file_path)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-1000:] or "ffprobe failed")
    data = json.loads(result.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "duration_seconds": float(data.get("format", {}).get("duration") or 0),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "audio_stream_count": sum(1 for stream in data.get("streams", []) if stream.get("codec_type") == "audio"),
    }
