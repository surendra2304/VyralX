import httpx
from app.config import get_settings

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def discover_youtube_videos(query: str, max_results: int = 10, order: str = "viewCount") -> list[dict]:
    settings = get_settings()
    if not settings.youtube_data_api_key:
        raise RuntimeError("Set YOUTUBE_DATA_API_KEY in the protected environment")
    max_results = max(1, min(int(max_results), 25))
    if order not in {"relevance", "date", "viewCount", "rating"}:
        raise ValueError("Unsupported YouTube search ordering")
    params = {"key": settings.youtube_data_api_key, "part": "snippet", "type": "video",
              "q": query[:200], "maxResults": max_results, "order": order,
              "safeSearch": "moderate"}
    with httpx.Client(timeout=20) as client:
        response = client.get(YOUTUBE_SEARCH_URL, params=params)
        response.raise_for_status()
        items = response.json().get("items", [])
        ids = [item.get("id", {}).get("videoId") for item in items]
        ids = [video_id for video_id in ids if video_id]
        if not ids:
            return []
        stats_response = client.get(YOUTUBE_VIDEOS_URL, params={
            "key": settings.youtube_data_api_key, "part": "statistics,contentDetails",
            "id": ",".join(ids)})
        stats_response.raise_for_status()
        stats = {item["id"]: item for item in stats_response.json().get("items", [])}
    candidates = []
    for item in items:
        video_id = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})
        metric = stats.get(video_id, {})
        statistics = metric.get("statistics", {})
        candidates.append({
            "video_id": video_id,
            "url": "https://www.youtube.com/watch?v=" + video_id,
            "title": snippet.get("title", ""),
            "channel_title": snippet.get("channelTitle", ""),
            "published_at": snippet.get("publishedAt", ""),
            "description": snippet.get("description", "")[:500],
            "view_count": int(statistics.get("viewCount", 0)),
            "like_count": int(statistics.get("likeCount", 0)),
            "comment_count": int(statistics.get("commentCount", 0)),
            "duration": metric.get("contentDetails", {}).get("duration", ""),
            "discovery_only": True,
            "rights_verified": False,
        })
    if order == "viewCount":
        return sorted(candidates, key=lambda x: x["view_count"], reverse=True)
    return candidates
