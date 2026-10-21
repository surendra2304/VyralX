"""Mixkit free stock video integration for authentic motion video clips."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from uuid import uuid4

import httpx

from app.config import get_settings
from app.services.probe import probe_media

log = logging.getLogger(__name__)

MIXKIT_SEARCH_URL = "https://mixkit.co/free-stock-video/"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def search_videos(query: str, *, max_results: int = 15) -> list[dict]:
    """Search Mixkit for free licensed stock video clips."""
    clean_query = " ".join(query.strip().split())
    if not clean_query:
        clean_query = "technology"

    url = f"{MIXKIT_SEARCH_URL}?q={clean_query}"
    try:
        with httpx.Client(timeout=12.0, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
            response = client.get(url)
            if response.status_code != 200:
                # Try fallback category path
                category = clean_query.split()[0].lower()
                cat_url = f"{MIXKIT_SEARCH_URL}{category}/"
                response = client.get(cat_url)
            if response.status_code != 200:
                log.warning("Mixkit search returned HTTP %d for query %r", response.status_code, clean_query)
                return []
            html = response.text
    except Exception as exc:
        log.warning("Mixkit search request failed for query %r: %s", clean_query, exc)
        return []

    # Extract unique video IDs from CDN paths in HTML
    pattern = r"https://assets\.mixkit\.co/videos/(\d+)/\1-360\.mp4"
    seen_ids: set[str] = set()
    results: list[dict] = []

    for match in re.finditer(pattern, html):
        vid = match.group(1)
        if vid in seen_ids:
            continue
        seen_ids.add(vid)
        results.append({
            "id": vid,
            "title": f"Mixkit Motion Video {vid} ({clean_query})",
            "download_url": f"https://assets.mixkit.co/videos/{vid}/{vid}-720.mp4",
            "fallback_url": f"https://assets.mixkit.co/videos/{vid}/{vid}-360.mp4",
            "source_url": f"https://mixkit.co/free-stock-video/{vid}/",
            "creator": "Mixkit Community",
            "creator_url": "https://mixkit.co/",
            "license": "Mixkit Free License",
        })
        if len(results) >= max_results:
            break

    return results


def import_video_file(
    video_id: str,
    download_url: str,
    *,
    fallback_url: str = "",
    title: str = "",
    max_bytes: int = 150 * 1024 * 1024,
) -> dict:
    """Download and register a Mixkit stock video clip."""
    settings = get_settings()
    dest_dir = settings.media_dir / "stock_videos"
    dest_dir.mkdir(parents=True, exist_ok=True)
    file_path = (dest_dir / f"mixkit-{video_id}-{uuid4().hex[:8]}.mp4").resolve()

    if dest_dir.resolve() not in file_path.parents:
        raise RuntimeError("Invalid video destination path")

    target_urls = [download_url]
    if fallback_url and fallback_url != download_url:
        target_urls.append(fallback_url)

    last_error: Exception | None = None
    downloaded = False

    for url in target_urls:
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
                with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        continue
                    content_length = resp.headers.get("content-length")
                    if content_length and int(content_length) > max_bytes:
                        raise ValueError(f"Video exceeds size limit ({content_length} bytes)")

                    total_bytes = 0
                    with open(file_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=65536):
                            total_bytes += len(chunk)
                            if total_bytes > max_bytes:
                                raise ValueError("Video exceeded size limit during stream")
                            f.write(chunk)
                    downloaded = True
                    break
        except Exception as exc:
            last_error = exc
            file_path.unlink(missing_ok=True)

    if not downloaded or not file_path.is_file() or file_path.stat().st_size <= 0:
        file_path.unlink(missing_ok=True)
        raise RuntimeError(f"Could not download Mixkit video {video_id}: {last_error}")

    try:
        metadata = probe_media(file_path)
    except Exception as probe_exc:
        file_path.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded video failed media probe: {probe_exc}") from probe_exc

    duration = float(metadata.get("duration_seconds") or 0.0)
    width = int(metadata.get("width") or 0)
    height = int(metadata.get("height") or 0)

    if duration <= 0 or width <= 0 or height <= 0:
        file_path.unlink(missing_ok=True)
        raise RuntimeError("Mixkit video had invalid duration or dimensions")

    return {
        "video_id": str(video_id),
        "file_path": str(file_path),
        "title": title or f"Mixkit Video {video_id}",
        "creator": "Mixkit Community",
        "creator_url": "https://mixkit.co/",
        "source_url": f"https://mixkit.co/free-stock-video/{video_id}/",
        "metadata": {
            "duration_seconds": duration,
            "width": width,
            "height": height,
        },
    }
