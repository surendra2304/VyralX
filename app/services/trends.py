"""Deterministic ranking for public discovery leads.

This module ranks leads; it never claims ownership rights and never downloads
third-party media. Scores are relative heuristics, not predictions of virality.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def _parse_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _age_hours(published_at: str | None, now: datetime) -> float | None:
    published = _parse_time(published_at)
    if published is None:
        return None
    return max(0.0, (now - published).total_seconds() / 3600)


def rank_candidates(
    candidates: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return copied candidates sorted by a bounded 0–100 heuristic score."""
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        views = max(0, int(candidate.get("view_count") or 0))
        likes = max(0, int(candidate.get("like_count") or 0))
        comments = max(0, int(candidate.get("comment_count") or 0))
        age_hours = _age_hours(candidate.get("published_at"), now)
        # Log scale reduces domination by legacy viral videos.
        reach_score = min(35.0, math.log10(views + 1) * 4.0)
        engagement_rate = (likes + 2 * comments) / max(views, 1)
        engagement_score = min(30.0, engagement_rate * 1000.0)
        recency_score = 0.0 if age_hours is None else 25.0 * math.exp(-age_hours / (24 * 7))
        completeness_score = 10.0 if candidate.get("title") and candidate.get("channel_title") else 0.0
        score = round(min(100.0, reach_score + engagement_score + recency_score + completeness_score), 2)
        enriched.append({
            **candidate,
            "trend_score": score,
            "engagement_rate": round(engagement_rate, 6),
            "age_hours": round(age_hours, 2) if age_hours is not None else None,
            "discovery_only": True,
            "rights_verified": False,
            "score_method": "reach_log+engagement+recency+metadata_v1",
        })
    return sorted(enriched, key=lambda item: item["trend_score"], reverse=True)
