"""Fetch public performance counters and synthesize audience intelligence feedback."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PublishJob, VideoMetric, utcnow
from app.services.peers import configured_peers, post_peer_json

log = logging.getLogger("vyralx.youtube_analytics")

VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def fetch_video_metrics(video_ids: list[str]) -> list[dict]:
    """Fetch public statistics from YouTube Data API v3."""
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
                    views = int(stats.get("viewCount", 0))
                    likes = int(stats.get("likeCount", 0))
                    comments = int(stats.get("commentCount", 0))
                    results.append({
                        "youtube_video_id": item.get("id", ""),
                        "title": item.get("snippet", {}).get("title", ""),
                        "view_count": views,
                        "like_count": likes,
                        "comment_count": comments,
                        "engagement_rate": calculate_engagement_rate(views, likes, comments),
                        "performance_tier": classify_performance_tier(views, likes, comments),
                    })
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"YouTube Data API returned HTTP {exc.response.status_code}") from None
    except httpx.RequestError as exc:
        raise RuntimeError(f"YouTube metrics request failed ({type(exc).__name__})") from None
    except ValueError:
        raise RuntimeError("YouTube Data API returned invalid JSON") from None
    return results


def calculate_engagement_rate(view_count: int, like_count: int, comment_count: int) -> float:
    """Calculate engagement rate percentage (likes + comments) / views with zero-safety."""
    views = max(0, int(view_count))
    if views == 0:
        return 0.0
    interactions = max(0, int(like_count)) + max(0, int(comment_count))
    rate = (interactions / views) * 100.0
    return round(min(100.0, rate), 2)


def classify_performance_tier(view_count: int, like_count: int, comment_count: int) -> str:
    """Categorize video into performance cohorts based on views and engagement."""
    views = max(0, int(view_count))
    engagement = calculate_engagement_rate(views, like_count, comment_count)

    if views >= 10000 or (views >= 2000 and engagement >= 10.0):
        return "breakout"
    if views >= 2000 or engagement >= 6.0:
        return "strong"
    if views >= 500 or engagement >= 3.0:
        return "healthy"
    return "underperforming"


def extract_top_performing_topics(metrics_records: list[dict[str, Any]], threshold_engagement: float = 4.0) -> list[str]:
    """Identify titles/topics that achieved high audience engagement."""
    high_performers = [
        str(r.get("title", "")).strip()
        for r in metrics_records
        if float(r.get("engagement_rate", 0)) >= threshold_engagement and r.get("title")
    ]
    return sorted(dict.fromkeys(high_performers))


def sync_video_metrics_batch(db: Session, video_ids: list[str]) -> dict[str, Any]:
    """Fetch metrics for published videos and persist or update in database."""
    metrics_data = fetch_video_metrics(video_ids)
    synced_count = 0
    now = utcnow()

    for item in metrics_data:
        vid = item["youtube_video_id"]
        # Look up corresponding publish job
        publish_job = db.scalar(
            select(PublishJob).where(PublishJob.youtube_video_id == vid).order_by(PublishJob.id.desc())
        )
        job_id = publish_job.id if publish_job else 0

        existing = db.scalar(select(VideoMetric).where(VideoMetric.youtube_video_id == vid))
        if existing is not None:
            existing.view_count = item["view_count"]
            existing.like_count = item["like_count"]
            existing.comment_count = item["comment_count"]
            existing.fetched_at = now
        else:
            metric = VideoMetric(
                publish_job_id=job_id,
                youtube_video_id=vid,
                view_count=item["view_count"],
                like_count=item["like_count"],
                comment_count=item["comment_count"],
                fetched_at=now,
            )
            db.add(metric)
        synced_count += 1

    db.commit()
    return {
        "status": "synced",
        "synced_count": synced_count,
        "metrics": metrics_data,
    }


def record_feedback_to_memora(
    project_id: int,
    youtube_video_id: str,
    title: str,
    stats: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch video performance learning memory to Memora for continuous agent improvement."""
    if "memora" not in configured_peers():
        return {"status": "skipped", "reason": "memora_peer_not_configured"}

    try:
        views = int(stats.get("view_count", 0))
        likes = int(stats.get("like_count", 0))
        comments = int(stats.get("comment_count", 0))
        rate = calculate_engagement_rate(views, likes, comments)
        tier = classify_performance_tier(views, likes, comments)

        memory_payload = {
            "source_agent": "vyralx",
            "category": "audience_performance",
            "title": f"Video Performance: {title[:80]}",
            "content": (
                f"Video ID: {youtube_video_id}\n"
                f"Project ID: {project_id}\n"
                f"Title: {title}\n"
                f"Performance Tier: {tier}\n"
                f"Views: {views:,} | Likes: {likes:,} | Comments: {comments:,}\n"
                f"Engagement Rate: {rate}%\n"
            ),
            "metadata": {
                "project_id": project_id,
                "youtube_video_id": youtube_video_id,
                "tier": tier,
                "engagement_rate": rate,
                "views": views,
            },
        }
        res = post_peer_json("memora", "/v1/memories", memory_payload, timeout_seconds=5.0)
        log.info("Performance feedback memory stored in Memora for project_id=%s tier=%s", project_id, tier)
        return {"status": "recorded", "memory_id": res.get("id"), "tier": tier}
    except Exception as exc:
        log.warning("Failed to record feedback memory to Memora: %s", exc)
        return {"status": "failed", "error": str(exc)}
