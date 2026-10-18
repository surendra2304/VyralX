"""Fetch public performance counters for VyralX's own published videos."""
from __future__ import annotations

import httpx

from app.config import get_settings

VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def fetch_video_metrics(video_ids: list[str]) -> list[dict]:
    settings = get_settings()
    if not settings.youtube_data_api_key:
        raise RuntimeError("Set YOUTUBE_DATA_API_KEY before refreshing YouTube metrics")
    ids = list(dict.fromkeys(value.strip() for value in video_ids if value and value.strip()))
    if not ids:
        return []
    results: list[dict] = []
    try:
        with httpx.Client(timeout=20) as client:
            for offset in range(0, len(ids), 50):
                response = client.get(
                    VIDEOS_URL,
                    params={
                        "key": settings.youtube_data_api_key,
                        "part": "statistics,snippet",
                        "id": ",".join(ids[offset:offset + 50]),
                    },
                )
                response.raise_for_status()
                items = response.json().get("items", [])
                for item in items:
                    stats = item.get("statistics", {})
                    results.append({
                        "youtube_video_id": item.get("id", ""),
                        "title": item.get("snippet", {}).get("title", ""),
                        "view_count": int(stats.get("viewCount", 0)),
                        "like_count": int(stats.get("likeCount", 0)),
                        "comment_count": int(stats.get("commentCount", 0)),
                    })
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"YouTube Data API returned HTTP {exc.response.status_code}") from None
    except httpx.RequestError as exc:
        raise RuntimeError(f"YouTube metrics request failed ({type(exc).__name__})") from None
    except ValueError:
        raise RuntimeError("YouTube Data API returned invalid JSON") from None
    return results
