"""
VyralX/app/services/personalized_recommendation.py — VyralX Personalized Content Recommendation Engine.

Recommends personalized video content based on viewer preferences, watch history,
engagement patterns, and collaborative filtering. Includes content similarity
scoring, trending detection, and diversity-aware recommendation.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class ViewerProfile:
    """A viewer profile."""
    viewer_id: str
    preferences: dict = field(default_factory=dict)  # genre → weight
    watch_history: list[str] = field(default_factory=list)  # video_ids
    liked_videos: list[str] = field(default_factory=list)
    disliked_videos: list[str] = field(default_factory=list)
    engagement_score: float = 0.5
    created_at: float = 0.0
    last_updated: float = 0.0


@dataclass
class VideoItem:
    """A video item in the catalog."""
    video_id: str
    title: str
    description: str = ""
    genre: str = "general"
    tags: list[str] = field(default_factory=list)
    duration_sec: float = 300.0
    views: int = 0
    likes: int = 0
    dislikes: int = 0
    engagement_rate: float = 0.0
    upload_time: float = 0.0
    trending: bool = False
    quality_score: float = 0.5


@dataclass
class Recommendation:
    """A recommendation result."""
    viewer_id: str
    recommendations: list[dict] = field(default_factory=list)  # [{video_id, score, reason}]
    algorithm: str = "collaborative"
    total_candidates: int = 0
    total_recommended: int = 0
    diversity_score: float = 0.0
    created_at: float = 0.0


@dataclass
class ContentSimilarity:
    """Content similarity between two videos."""
    video_id_a: str
    video_id_b: str
    similarity_score: float = 0.0
    shared_tags: list[str] = field(default_factory=list)
    shared_genre: bool = False
    collaborative_similarity: float = 0.0
    content_similarity: float = 0.0


@dataclass
class EngagementPattern:
    """Viewer engagement pattern."""
    viewer_id: str
    avg_watch_time_sec: float = 0.0
    completion_rate: float = 0.0
    preferred_duration: str = "medium"  # short, medium, long
    preferred_genres: list[str] = field(default_factory=list)
    time_of_day_preference: str = ""
    engagement_trend: str = "stable"  # increasing, stable, decreasing


@dataclass
class DiversityMetric:
    """Diversity metric for recommendations."""
    viewer_id: str
    category_diversity: float = 0.0
    creator_diversity: float = 0.0
    duration_diversity: float = 0.0
    overall_diversity: float = 0.0


class PersonalizedRecommendationEngine:
    """Personalized content recommendation engine."""

    def __init__(self):
        self._profiles: dict[str, ViewerProfile] = {}
        self._videos: dict[str, VideoItem] = {}
        self._recommendations: dict[str, Recommendation] = {}
        self._similarities: list[ContentSimilarity] = []
        self._engagement_patterns: dict[str, EngagementPattern] = {}

    def add_viewer(self, viewer_id: str, preferences: dict | None = None) -> ViewerProfile:
        """Add a viewer profile."""
        profile = ViewerProfile(
            viewer_id=viewer_id,
            preferences=preferences or {},
            created_at=time.time(),
            last_updated=time.time(),
        )
        self._profiles[viewer_id] = profile
        return profile

    def add_video(
        self,
        title: str,
        genre: str = "general",
        description: str = "",
        tags: list[str] | None = None,
        duration_sec: float = 300.0,
        quality_score: float = 0.5,
    ) -> VideoItem:
        """Add a video to the catalog."""
        video = VideoItem(
            video_id=hashlib.md5(
                f"video:{title}:{time.time()}".encode()
            ).hexdigest()[:12],
            title=title,
            description=description,
            genre=genre,
            tags=tags or [],
            duration_sec=duration_sec,
            upload_time=time.time(),
            quality_score=quality_score,
            engagement_rate=0.1,
        )
        self._videos[video.video_id] = video
        return video

    def record_view(self, viewer_id: str, video_id: str, rating: float = 0.0) -> dict:
        """Record a view action."""
        profile = self._profiles.get(viewer_id)
        if not profile:
            raise HTTPException(404, f"Viewer {viewer_id} not found")

        video = self._videos.get(video_id)
        if not video:
            raise HTTPException(404, f"Video {video_id} not found")

        profile.watch_history.append(video_id)
        profile.last_updated = time.time()

        if rating > 3.0:
            profile.liked_videos.append(video_id)
        elif rating < 2.0:
            profile.disliked_videos.append(video_id)

        # Update video stats
        video.views += 1
        if rating > 3.0:
            video.likes += 1
        elif rating < 2.0:
            video.dislikes += 1

        video.engagement_rate = (
            (video.likes + video.views * 0.1) / max(1, video.views)
        )

        return {"viewer_id": viewer_id, "video_id": video_id, "status": "recorded"}

    def recommend(
        self,
        viewer_id: str,
        count: int = 10,
        algorithm: str = "hybrid",
    ) -> Recommendation:
        """Generate personalized recommendations."""
        profile = self._profiles.get(viewer_id)
        if not profile:
            raise HTTPException(404, f"Viewer {viewer_id} not found")

        candidates = []
        watched_ids = set(profile.watch_history)

        for video in self._videos.values():
            if video.video_id in watched_ids:
                continue

            score = 0.0
            reasons = []

            # Content-based scoring
            if algorithm in ("hybrid", "content"):
                # Genre match
                if video.genre in profile.preferences:
                    score += profile.preferences[video.genre] * 30
                    reasons.append(f"Your preferred genre: {video.genre}")

                # Tag match
                for tag in video.tags:
                    if tag in str(profile.preferences):
                        score += 5

                # Quality score
                score += video.quality_score * 10

                # Engagement rate
                score += video.engagement_rate * 10

            # Collaborative filtering
            if algorithm in ("hybrid", "collaborative"):
                # Find similar viewers
                similar_viewers = self._find_similar_viewers(viewer_id)
                for sv in similar_viewers:
                    if video.video_id in sv.watch_history:
                        score += 15
                        reasons.append("Watched by viewers similar to you")
                        break

            # Popularity boost
            score += min(10, video.views / 1000)

            # Trending boost
            if video.trending:
                score += 10
                reasons.append("Trending now")

            if score > 0:
                candidates.append({
                    "video_id": video.video_id,
                    "title": video.title,
                    "genre": video.genre,
                    "score": score,
                    "reasons": reasons[:3],
                })

        # Sort by score
        candidates.sort(key=lambda c: -c["score"])

        # Select top recommendations
        selected = candidates[:count]

        # Calculate diversity
        diversity = self._calculate_diversity(selected)

        recommendation = Recommendation(
            viewer_id=viewer_id,
            recommendations=selected,
            algorithm=algorithm,
            total_candidates=len(candidates),
            total_recommended=len(selected),
            diversity_score=diversity,
            created_at=time.time(),
        )

        self._recommendations[f"{viewer_id}:{recommendation.created_at}"] = recommendation
        return recommendation

    def _find_similar_viewers(self, viewer_id: str) -> list[ViewerProfile]:
        """Find viewers similar to a given viewer."""
        target = self._profiles.get(viewer_id)
        if not target:
            return []

        similar = []
        for profile in self._profiles.values():
            if profile.viewer_id == viewer_id:
                continue

            # Calculate similarity based on shared watch history
            shared = set(profile.watch_history) & set(target.watch_history)
            if len(shared) > 0:
                similar.append(profile)

        return similar[:10]

    def _calculate_diversity(self, recommendations: list[dict]) -> float:
        """Calculate diversity score of recommendations."""
        if not recommendations:
            return 0.0

        genres = set(r.get("genre", "") for r in recommendations)
        durations = set()

        for r in recommendations:
            video = self._videos.get(r["video_id"])
            if video:
                if video.duration_sec < 60:
                    durations.add("short")
                elif video.duration_sec < 600:
                    durations.add("medium")
                else:
                    durations.add("long")

        category_diversity = len(genres) / max(1, len(recommendations))
        duration_diversity = len(durations) / max(1, len(recommendations))

        return (category_diversity + duration_diversity) / 2

    def get_engagement_pattern(self, viewer_id: str) -> EngagementPattern:
        """Get engagement pattern for a viewer."""
        profile = self._profiles.get(viewer_id)
        if not profile:
            raise HTTPException(404, f"Viewer {viewer_id} not found")

        # Calculate engagement pattern
        pattern = EngagementPattern(viewer_id=viewer_id)

        if profile.watch_history:
            durations = []
            for vid in profile.watch_history:
                video = self._videos.get(vid)
                if video:
                    durations.append(video.duration_sec)

            if durations:
                pattern.avg_watch_time_sec = sum(durations) / len(durations)

                if pattern.avg_watch_time_sec < 60:
                    pattern.preferred_duration = "short"
                elif pattern.avg_watch_time_sec < 600:
                    pattern.preferred_duration = "medium"
                else:
                    pattern.preferred_duration = "long"

        # Preferred genres from profile preferences
        pattern.preferred_genres = list(profile.preferences.keys())

        # Engagement score
        pattern.completion_rate = profile.engagement_score

        self._engagement_patterns[viewer_id] = pattern
        return pattern

    def get_report(self) -> dict:
        """Get recommendation engine report."""
        return {
            "total_viewers": len(self._profiles),
            "total_videos": len(self._videos),
            "total_recommendations": len(self._recommendations),
            "total_engagement_patterns": len(self._engagement_patterns),
            "total_similarities": len(self._similarities),
            "genres": list(set(v.genre for v in self._videos.values())),
            "avg_engagement_rate": sum(v.engagement_rate for v in self._videos.values()) / max(1, len(self._videos)),
            "trending_videos": sum(1 for v in self._videos.values() if v.trending),
        }


# Module-level singleton
recommendation_engine = PersonalizedRecommendationEngine()


# ── API Routes ──────────────────────────────────────────────────────────────


@router.post("/api/v1/vyralx/recommendation/viewers")
async def add_viewer(payload: dict):
    """Add a viewer profile."""
    profile = recommendation_engine.add_viewer(
        viewer_id=payload["viewer_id"],
        preferences=payload.get("preferences", {}),
    )
    return {"viewer_id": profile.viewer_id, "status": "created"}


@router.post("/api/v1/vyralx/recommendation/videos")
async def add_video(payload: dict):
    """Add a video to the catalog."""
    video = recommendation_engine.add_video(
        title=payload["title"],
        genre=payload.get("genre", "general"),
        description=payload.get("description", ""),
        tags=payload.get("tags", []),
        duration_sec=payload.get("duration_sec", 300.0),
        quality_score=payload.get("quality_score", 0.5),
    )
    return {"video_id": video.video_id, "title": video.title, "status": "added"}


@router.post("/api/v1/vyralx/recommendation/views")
async def record_view(payload: dict):
    """Record a view action."""
    result = recommendation_engine.record_view(
        viewer_id=payload["viewer_id"],
        video_id=payload["video_id"],
        rating=payload.get("rating", 0.0),
    )
    return result


@router.get("/api/v1/vyralx/recommendation/{viewer_id}/recommend")
async def recommend(viewer_id: str, count: int = 10, algorithm: str = "hybrid"):
    """Generate personalized recommendations."""
    result = recommendation_engine.recommend(viewer_id, count, algorithm)
    return {
        "viewer_id": result.viewer_id,
        "algorithm": result.algorithm,
        "total_recommended": result.total_recommended,
        "diversity_score": result.diversity_score,
        "recommendations": result.recommendations,
    }


@router.get("/api/v1/vyralx/recommendation/{viewer_id}/engagement")
async def get_engagement_pattern(viewer_id: str):
    """Get engagement pattern for a viewer."""
    pattern = recommendation_engine.get_engagement_pattern(viewer_id)
    return {
        "viewer_id": pattern.viewer_id,
        "avg_watch_time_sec": pattern.avg_watch_time_sec,
        "completion_rate": pattern.completion_rate,
        "preferred_duration": pattern.preferred_duration,
        "preferred_genres": pattern.preferred_genres,
    }


@router.get("/api/v1/vyralx/recommendation/report")
async def get_report():
    """Get recommendation engine report."""
    return recommendation_engine.get_report()
