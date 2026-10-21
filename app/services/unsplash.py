"""Official Unsplash photo discovery and authorized editorial stock import."""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.config import get_settings
from app.services.probe import probe_media

log = logging.getLogger("vyralx.unsplash")

UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"


def _access_key() -> str:
    key = get_settings().unsplash_access_key.strip()
    if not key:
        raise RuntimeError("Set UNSPLASH_ACCESS_KEY to enable licensed Unsplash stock discovery")
    return key


def _safe_image_url(url: str) -> bool:
    """Accept only credential-free HTTPS URLs on trusted Unsplash hosts."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold()
        port = parsed.port
    except (TypeError, ValueError):
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
    return host == "unsplash.com" or host.endswith(".unsplash.com")


def search_photos(
    query: str,
    *,
    orientation: str = "portrait",
    per_page: int = 10,
) -> list[dict]:
    """Search Unsplash for high-resolution photographs matching video montage scenes."""
    key = _access_key()
    clean_query = str(query).strip()
    if not clean_query:
        raise ValueError("query cannot be empty")

    orient = orientation.lower().strip()
    if orient not in {"portrait", "landscape", "squarish"}:
        orient = "portrait"

    params = {
        "query": clean_query[:200],
        "orientation": orient,
        "per_page": max(1, min(int(per_page), 30)),
    }
    headers = {
        "Authorization": f"Client-ID {key}",
        "Accept-Version": "v1",
    }

    try:
        response = httpx.get(
            UNSPLASH_SEARCH_URL,
            params=params,
            headers=headers,
            timeout=20.0,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Unsplash API returned HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise RuntimeError(f"Unsplash search request failed: {exc}") from exc

    data = response.json()
    results = data.get("results") or []
    items = []
    for photo in results:
        urls = photo.get("urls") or {}
        download_url = urls.get("regular") or urls.get("full") or urls.get("small")
        if not download_url:
            continue
        user = photo.get("user") or {}
        creator_name = str(user.get("name") or user.get("username") or "Unsplash Photographer").strip()
        photo_id = str(photo.get("id") or "").strip()
        items.append({
            "id": photo_id,
            "title": str(photo.get("alt_description") or photo.get("description") or f"Photo by {creator_name}").strip(),
            "description": str(photo.get("description") or "").strip(),
            "width": int(photo.get("width") or 0),
            "height": int(photo.get("height") or 0),
            "creator": creator_name,
            "creator_url": str((user.get("links") or {}).get("html") or f"https://unsplash.com/@{user.get('username', '')}"),
            "download_url": download_url,
            "page_url": str((photo.get("links") or {}).get("html") or f"https://unsplash.com/photos/{photo_id}"),
            "download_location": str((photo.get("links") or {}).get("download_location") or ""),
            "license": "Unsplash License (free commercial use)",
        })
    return items


def import_photo(
    photo_id: str,
    download_url: str,
    *,
    title: str = "",
    creator: str = "",
    creator_url: str = "",
    max_bytes: int = 150 * 1024 * 1024,
) -> dict:
    """Download an authorized Unsplash photograph into VyralX media storage."""
    clean_url = str(download_url).strip()
    if not _safe_image_url(clean_url):
        raise ValueError(f"URL authority is not a permitted Unsplash domain: {clean_url}")

    settings = get_settings()
    out_dir = settings.media_dir / "unsplash"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest_path = (out_dir / f"unsplash_{photo_id}_{uuid4().hex[:8]}.jpg").resolve()
    if out_dir.resolve() not in dest_path.parents:
        raise RuntimeError("Invalid Unsplash destination path")

    try:
        with httpx.stream("GET", clean_url, timeout=30.0, follow_redirects=True) as stream:
            stream.raise_for_status()
            content_type = stream.headers.get("content-type", "").lower()
            if not any(t in content_type for t in ("image/", "application/octet-stream")):
                raise ValueError(f"Content-Type is not an image: {content_type}")
            bytes_written = 0
            with dest_path.open("wb") as handle:
                for chunk in stream.iter_bytes(chunk_size=1024 * 1024):
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        raise ValueError(f"Unsplash download exceeded size limit of {max_bytes} bytes")
                    handle.write(chunk)
    except Exception:
        dest_path.unlink(missing_ok=True)
        raise

    meta = probe_media(dest_path)
    return {
        "file_path": str(dest_path),
        "file_size": dest_path.stat().st_size,
        "width": int(meta.get("width") or 0),
        "height": int(meta.get("height") or 0),
        "duration_seconds": 0.0,
        "title": title or f"Unsplash photo {photo_id}",
        "creator": creator or "Unsplash Photographer",
        "source_url": f"https://unsplash.com/photos/{photo_id}",
        "creator_url": creator_url or "https://unsplash.com",
        "license_name": "Unsplash License",
        "platform": "unsplash",
    }
