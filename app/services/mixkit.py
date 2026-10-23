"""Mixkit free stock video integration for authentic motion video clips."""
from __future__ import annotations

import logging
import re
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

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "by", "why", "how", "what", "is", "are", "inside", "your", "people", "trades",
    "never", "from", "this", "that", "these", "those", "second", "work", "life",
    "hour", "build", "subscribe", "elite", "secrets", "secret", "shocking", "percent", "does",
    "doesn", "come", "just", "like", "even", "more", "into", "video", "scene", "short",
    "shorts", "about", "looking", "facing", "doing", "slowly", "seen", "very",
    "class", "middle", "did", "know", "alien", "trade", "stop", "selling", "trap", "exploit",
}

FOOTER_FALLBACK_IDS = {"41576", "2213", "4119", "4075", "1610"}

CONCEPT_MAP: dict[str, list[str]] = {
    "dna": ["microscope", "laboratory", "chemistry", "science"],
    "genetic": ["microscope", "laboratory", "cells"],
    "ancestor": ["earth", "space", "science"],
    "biology": ["microscope", "laboratory", "chemistry"],
    "cellular": ["microscope", "chemistry"],
    "brain": ["technology", "programming", "science"],
    "software": ["technology", "programming", "data-center"],
    "wealth": ["money", "cash", "dollars", "stock-market"],
    "billionaire": ["money", "cash", "dollars"],
    "hours": ["money", "stock-market", "investor"],
    "asymmetric": ["stock-market", "trading", "investor"],
    "investor": ["stock-market", "investor", "money"],
    "portfolio": ["stock-market", "investor"],
    "dollar": ["money", "cash", "dollars"],
    "income": ["money", "stock-market", "cash"],
    "trading": ["stock-market", "investor"],
    "stock": ["stock-market", "investor"],
    "capital": ["money", "stock-market", "cash"],
    "server": ["data-center", "server-room", "technology"],
    "data": ["data-center", "technology", "programming"],
    "code": ["programming", "technology"],
    "earth": ["earth", "space"],
    "space": ["space", "nebula", "earth"],
    "universe": ["space", "nebula"],
    "humanity": ["earth", "space", "science"],
}


def search_videos(query: str, *, max_results: int = 15) -> list[dict]:
    """Search Mixkit for topic-relevant licensed motion stock video clips."""
    clean_query = " ".join(query.strip().split())
    if not clean_query:
        clean_query = "technology"

    words = [
        w.lower()
        for w in re.findall(r"[A-Za-z0-9]+", clean_query)
        if len(w) >= 3 and w.lower() not in STOPWORDS
    ]
    if not words:
        words = ["technology", "business"]

    search_terms = []
    # Compound 2-word phrase if available
    if len(words) >= 2:
        search_terms.append(f"{words[0]}-{words[1]}")
        search_terms.append(f"{words[0]} {words[1]}")
    search_terms.extend(words[:4])

    for w in words:
        if w in CONCEPT_MAP:
            for mapped in CONCEPT_MAP[w]:
                if mapped not in search_terms:
                    search_terms.append(mapped)

    candidates: list[tuple[int, dict]] = []
    seen_ids: set[str] = set()

    with httpx.Client(timeout=10.0, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
        for term in search_terms:
            endpoints = [
                f"{MIXKIT_SEARCH_URL}{term.replace(' ', '-')}/",
                f"{MIXKIT_SEARCH_URL}?q={term}",
            ]
            for url in endpoints:
                try:
                    response = client.get(url)
                    if response.status_code != 200:
                        continue
                    # Ignore Mixkit redirect to discover / no results page which serves random popular clips
                    if "/discover/" in str(response.url) or "no results" in response.text.lower():
                        continue
                    html = response.text
                    matches = re.findall(
                        r'href=[\"\']/free-stock-video/([a-zA-Z0-9\-]+)-(\d+)/[\"\']', html
                    )
                    for slug, vid in matches:
                        if vid in seen_ids or vid in FOOTER_FALLBACK_IDS:
                            continue
                        seen_ids.add(vid)
                        title = slug.replace("-", " ").strip().title()
                        title_lower = title.lower()
                        term_clean = term.replace("-", " ").lower()
                        # Strict relevance check: Must contain at least one query word or the concept term
                        term_matches = term_clean in title_lower or any(p in title_lower for p in term_clean.split() if len(p) >= 3)
                        word_matches = [w for w in words if w in title_lower]
                        if not term_matches and not word_matches:
                            continue
                        score = len(word_matches) * 3 + (2 if term_clean in title_lower else 1)
                        candidates.append((score, {
                            "id": vid,
                            "title": title,
                            "download_url": f"https://assets.mixkit.co/videos/{vid}/{vid}-720.mp4",
                            "fallback_url": f"https://assets.mixkit.co/videos/{vid}/{vid}-360.mp4",
                            "source_url": f"https://mixkit.co/free-stock-video/{vid}/",
                            "creator": "Mixkit Community",
                            "creator_url": "https://mixkit.co/",
                            "license": "Mixkit Free License",
                        }))
                except Exception as exc:
                    log.debug("Mixkit search attempt failed for %s: %s", url, exc)
                if len(candidates) >= max_results * 2:
                    break
            if len(candidates) >= max_results:
                break

    candidates.sort(key=lambda c: c[0], reverse=True)
    results = [c[1] for c in candidates[:max_results]]

    # Absolute fallback if network blocked topic searches
    if not results:
        fallback_id = "41576"
        results.append({
            "id": fallback_id,
            "title": f"Mixkit Motion Video {fallback_id}",
            "download_url": f"https://assets.mixkit.co/videos/{fallback_id}/{fallback_id}-720.mp4",
            "fallback_url": f"https://assets.mixkit.co/videos/{fallback_id}/{fallback_id}-360.mp4",
            "source_url": f"https://mixkit.co/free-stock-video/{fallback_id}/",
            "creator": "Mixkit Community",
            "creator_url": "https://mixkit.co/",
            "license": "Mixkit Free License",
        })

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
