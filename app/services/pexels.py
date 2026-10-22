"""Official Pexels video search and authorized stock-footage import."""
from __future__ import annotations

from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.config import get_settings
from app.services.probe import probe_media

PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"
PEXELS_VIDEO_URL = "https://api.pexels.com/videos/videos/{video_id}"


def _api_key() -> str:
    key = get_settings().pexels_api_key.strip()
    if not key:
        raise RuntimeError("Set PEXELS_API_KEY to enable licensed stock-footage discovery")
    return key


def _safe_file_url(url: str) -> bool:
    """Accept only credential-free HTTPS URLs on known media hosts and default ports."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold()
        port = parsed.port
    except (TypeError, ValueError):
        # Malformed IPv6 authorities and non-numeric ports must fail closed.
        return False
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.netloc.endswith(":")
        or parsed.fragment
    ):
        return False
    if host == "pexels.com" or host.endswith(".pexels.com"):
        return True
    # Some official Pexels API responses use Vimeo's player CDN for media files.
    return host == "player.vimeo.com" and parsed.path.startswith("/external/")


def _normalize_video(video: dict) -> dict:
    files = []
    for video_file in video.get("video_files", []):
        if video_file.get("file_type") != "video/mp4":
            continue
        files.append({
            "id": int(video_file["id"]),
            "width": int(video_file.get("width") or 0),
            "height": int(video_file.get("height") or 0),
            "quality": str(video_file.get("quality") or "unknown"),
            "file_type": "video/mp4",
        })
    files.sort(key=lambda item: (item["width"] * item["height"], item["width"]), reverse=True)
    user = video.get("user") or {}
    return {
        "video_id": int(video["id"]),
        "url": str(video.get("url") or ""),
        "creator": str(user.get("name") or "Unknown"),
        "creator_url": str(user.get("url") or ""),
        "duration_seconds": int(video.get("duration") or 0),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "video_files": files,
        "provider": "Pexels",
        "license_url": "https://www.pexels.com/license/",
        "rights_verified": False,
        "notice": "Search result only. Review the Pexels license and source page before import.",
    }


def search_videos(
    query: str,
    *,
    max_results: int = 10,
    orientation: str = "portrait",
) -> list[dict]:
    if orientation not in {"portrait", "landscape", "square"}:
        raise ValueError("orientation must be portrait, landscape, or square")
    params = {"query": query[:200], "per_page": max(1, min(int(max_results), 25)), "orientation": orientation}
    try:
        response = httpx.get(
            PEXELS_SEARCH_URL,
            headers={"Authorization": _api_key()},
            params=params,
            timeout=20,
            follow_redirects=False,
        )
        response.raise_for_status()
        items = response.json().get("videos", [])
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Pexels returned HTTP {exc.response.status_code}") from None
    except httpx.RequestError as exc:
        raise RuntimeError(f"Pexels request failed ({type(exc).__name__})") from None
    except ValueError:
        raise RuntimeError("Pexels returned invalid JSON") from None
    return [_normalize_video(item) for item in items if item.get("id") and item.get("url")]


def import_video_file(video_id: int, file_id: int, *, title: str, max_bytes: int) -> dict:
    """Download only an API-returned Pexels MP4 URL, with a strict size limit."""
    settings = get_settings()
    headers = {"Authorization": _api_key()}
    try:
        response = httpx.get(
            PEXELS_VIDEO_URL.format(video_id=int(video_id)),
            headers=headers,
            timeout=20,
            follow_redirects=False,
        )
        response.raise_for_status()
        video = response.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Pexels video lookup returned HTTP {exc.response.status_code}") from None
    except httpx.RequestError as exc:
        raise RuntimeError(f"Pexels video lookup failed ({type(exc).__name__})") from None
    except ValueError:
        raise RuntimeError("Pexels returned invalid video metadata") from None

    candidate = next(
        (item for item in video.get("video_files", [])
         if int(item.get("id", -1)) == int(file_id) and item.get("file_type") == "video/mp4"),
        None,
    )
    if candidate is None:
        raise ValueError("video_file_id is not a downloadable MP4 for this Pexels video")
    file_url = str(candidate.get("link") or "")
    if not _safe_file_url(file_url):
        raise RuntimeError("Pexels returned a media URL outside the approved HTTPS domain")
    destination = (settings.media_dir / (uuid4().hex + ".mp4")).resolve()
    if settings.media_dir.resolve() not in destination.parents:
        raise RuntimeError("Invalid media destination path")

    written = 0
    try:
        # Follow redirects manually and revalidate every target. Provider CDNs may
        # redirect once, but an arbitrary Location must never become an SSRF path.
        current_url = file_url
        with httpx.Client(timeout=60, follow_redirects=False) as client:
            media_response = None
            for _ in range(4):
                request = client.build_request(
                    "GET", current_url, headers={"User-Agent": "VyralX/1.0"}
                )
                response = client.send(request, stream=True)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location", "")
                    response.close()
                    if not location:
                        raise RuntimeError("Pexels CDN returned a redirect without Location")
                    next_url = httpx.URL(current_url).join(location).human_repr()
                    if not _safe_file_url(next_url):
                        raise RuntimeError("Pexels CDN redirect target is outside the approved HTTPS domain")
                    current_url = next_url
                    continue
                response.raise_for_status()
                media_response = response
                break
            if media_response is None:
                raise RuntimeError("Pexels CDN exceeded the redirect limit")
            try:
                content_length = media_response.headers.get("content-length")
                if content_length and int(content_length) > max_bytes:
                    raise ValueError("Selected Pexels video exceeds MAX_STOCK_CLIP_MB")
                with destination.open("wb") as output:
                    for chunk in media_response.iter_bytes(chunk_size=1024 * 1024):
                        written += len(chunk)
                        if written > max_bytes:
                            raise ValueError("Selected Pexels video exceeds MAX_STOCK_CLIP_MB")
                        output.write(chunk)
            finally:
                media_response.close()
        if written == 0:
            raise RuntimeError("Pexels returned an empty media file")
        metadata = probe_media(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {
        "file_path": str(destination),
        "title": title[:300],
        "metadata": metadata,
        "file_id": int(file_id),
        "video_id": int(video_id),
        "source_url": str(video.get("url") or f"https://www.pexels.com/video/{video_id}/"),
        "creator": str((video.get("user") or {}).get("name") or "Unknown"),
        "creator_url": str((video.get("user") or {}).get("url") or ""),
    }
