"""
VyralX/app/services/viral_predictor.py — VyralX Viral Content Predictor.

Extends VyralX's capabilities with:
1. Viral Potential Scoring: score content's viral potential
2. Trend Detection: detect emerging trends
3. Content Similarity Analysis: find similar viral content
4. Viral Pattern Learning: learn what makes content go viral
5. Shareability Analysis: analyze content's shareability factors
6. Optimal Post Timing: find best times to post
7. Viral Cycle Prediction: predict viral lifecycle
"""
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class ViralScore:
    """Viral potential score."""
    content_id: str
    score: float  # 0-100
    factors: dict[str, float]
    viral_class: str  # mega_viral, viral, potential, normal, low
    predicted_shares: int
    predicted_views: int
    predicted_timeframe: str  # hours, days, weeks
    confidence: float


@dataclass
class Trend:
    """Detected trend."""
    topic: str
    category: str
    momentum: float  # 0-1
    growth_rate: float  # percentage
    peak_engagement: float
    related_hashtags: list[str]
    similar_content: list[str]
    detected_at: float
    forecast: str


@dataclass
class ViralPattern:
    """Learned viral pattern."""
    pattern_id: str
    description: str
    common_elements: list[str]
    success_rate: float
    examples: list[str]
    learned_at: float


@dataclass
class ShareabilityAnalysis:
    """Content shareability analysis."""
    content_id: str
    score: float
    emotional_triggers: list[str]
    share_factors: list[str]
    shares_by_platform: dict[str, int]
    optimal_hook: str
    recommendation: str


@dataclass
class PostTiming:
    """Optimal post timing."""
    platform: str
    best_times: list[str]
    worst_times: list[str]
    timezone: str = "UTC"
    confidence: float = 0.5
    rationale: str = ""


@dataclass
class ViralLifecycle:
    """Viral content lifecycle prediction."""
    content_id: str
    phases: list[dict]
    peak_time: float
    total_duration: float
    peak_shares: int
    total_shares: int
    decay_rate: float


@dataclass
class ContentSimilarity:
    """Content similarity analysis."""
    content_id: str
    similar: list[dict]
    shared_elements: list[str]
    similarity_score: float


class ViralPredictor:
    """Viral content prediction engine."""

    def __init__(self):
        self._scores: dict[str, ViralScore] = {}
        self._trends: list[Trend] = []
        self._patterns: list[ViralPattern] = []
        self._similarity: dict[str, ContentSimilarity] = {}
        self._lifecycles: dict[str, ViralLifecycle] = {}

    # ── Viral Potential Scoring ───────────────────────────────────────────

    def score_viral_potential(
        self,
        content_id: str,
        content: dict,
    ) -> ViralScore:
        """Score content's viral potential."""
        factors = {}

        # Emotional triggers
        emotion_words = {
            "awe": ["amazing", "incredible", "wow", "mind-blowing"],
            "joy": ["happy", "love", "fun", "excited"],
            "surprise": ["unexpected", "shocking", "surprise"],
            "inspiration": ["motivating", "inspiring", "success"],
            "urgency": ["now", "urgent", "don't miss", "limited"],
            "controversy": ["debate", "controversial", "hot take"],
        }

        body_lower = content.get("body", "").lower()

        for emotion, words in emotion_words.items():
            count = sum(1 for w in words if w in body_lower)
            factors[emotion] = min(1.0, count * 0.3)

        # Engagement signals
        factors["has_hook"] = 1.0 if self._has_hook(content) else 0.0
        factors["has_visual"] = 1.0 if content.get("has_visual", False) else 0.5
        factors["length_optimal"] = self._length_score(content)
        factors["platform_fit"] = self._platform_fit(content, content.get("platform", ""))

        # Calculate score
        weights = {
            "awe": 0.15,
            "joy": 0.15,
            "surprise": 0.10,
            "inspiration": 0.15,
            "urgency": 0.10,
            "controversy": 0.10,
            "has_hook": 0.10,
            "has_visual": 0.05,
            "length_optimal": 0.05,
            "platform_fit": 0.05,
        }

        score = sum(factors.get(k, 0) * w for k, w in weights.items()) * 100

        # Viral class
        if score > 80:
            viral_class = "mega_viral"
        elif score > 60:
            viral_class = "viral"
        elif score > 40:
            viral_class = "potential"
        elif score > 20:
            viral_class = "normal"
        else:
            viral_class = "low"

        # Predict reach
        base_views = {
            "twitter": 1000,
            "instagram": 5000,
            "youtube": 500,
            "tiktok": 10000,
        }
        platform = content.get("platform", "")
        base = base_views.get(platform, 1000)
        predicted_shares = int(base * score / 100 * 0.3)
        predicted_views = int(predicted_shares * 5)

        if score > 80:
            timeframe = "hours"
        elif score > 60:
            timeframe = "days"
        else:
            timeframe = "weeks"

        result = ViralScore(
            content_id=content_id,
            score=score,
            factors=factors,
            viral_class=viral_class,
            predicted_shares=predicted_shares,
            predicted_views=predicted_views,
            predicted_timeframe=timeframe,
            confidence=min(0.9, 0.5 + score / 200),
        )

        self._scores[content_id] = result
        return result

    def _has_hook(self, content: dict) -> bool:
        """Check if content has a strong hook."""
        title = content.get("title", "").lower()
        # Check for patterns
        hooks = [
            "you won't believe",
            "this is why",
            "the truth about",
            "how to",
            "why this matters",
            "what happens next",
        ]
        return any(h in title for h in hooks)

    def _length_score(self, content: dict) -> float:
        """Score content length optimality."""
        word_count = len(content.get("body", "").split())
        platform = content.get("platform", "")

        optimal_ranges = {
            "twitter": (50, 200),
            "instagram": (100, 300),
            "youtube": (500, 2000),
            "tiktok": (30, 150),
            "blog": (500, 3000),
        }

        range = optimal_ranges.get(platform, (50, 500))
        if range[0] <= word_count <= range[1]:
            return 1.0
        elif word_count < range[0] * 0.5:
            return 0.3
        elif word_count > range[1] * 2:
            return 0.5
        else:
            return 0.7

    def _platform_fit(self, content: dict, platform: str) -> float:
        """Score platform fit."""
        format = content.get("format", "")
        platform_formats = {
            "twitter": ["text", "thread"],
            "instagram": ["image", "reel", "carousel"],
            "youtube": ["video"],
            "tiktok": ["video"],
            "blog": ["article"],
        }

        expected = platform_formats.get(platform, [])
        if not expected:
            return 0.5

        if format in expected:
            return 1.0

        return 0.4

    # ── Trend Detection ───────────────────────────────────────────────────

    def detect_trends(
        self,
        posts: list[dict],
        window_hours: float = 24,
    ) -> list[Trend]:
        """Detect emerging trends."""
        now = time.time()
        cutoff = now - window_hours * 3600

        # Group by topic/hashtag
        topic_counts = {}
        topic_engagement = {}

        for post in posts:
            ts = post.get("timestamp", now)
            if ts < cutoff:
                continue

            topic = post.get("topic", "")
            hashtags = post.get("hashtags", [])
            engagement = post.get("engagement", 0)

            for t in [topic] + hashtags:
                if t:
                    topic_counts[t] = topic_counts.get(t, 0) + 1
                    topic_engagement[t] = topic_engagement.get(t, 0) + engagement

        # Calculate momentum
        trends = []
        for topic, count in topic_counts.items():
            if count < 3:
                continue

            momentum = min(1.0, count / 20)
            growth = (count / max(1, topic_counts.get(topic, 1)) - 1) * 100

            trend = Trend(
                topic=topic,
                category=self._categorize_trend(topic),
                momentum=momentum,
                growth_rate=growth,
                peak_engagement=topic_engagement.get(topic, 0) / count,
                related_hashtags=[f"#{topic}"],
                similar_content=[],
                detected_at=time.time(),
                forecast=self._forecast_trend(momentum, growth),
            )

            trends.append(trend)

        # Sort by momentum
        trends.sort(key=lambda t: -t.momentum)
        self._trends.extend(trends)

        return trends[:20]

    def _categorize_trend(self, topic: str) -> str:
        topic_lower = topic.lower()
        categories = {
            "tech": ["ai", "tech", "crypto", "blockchain", "software"],
            "entertainment": ["movie", "music", "game", "celebrity", "viral"],
            "lifestyle": ["food", "travel", "fashion", "fitness", "wellness"],
            "business": ["startup", "business", "marketing", "sales", "economy"],
            "social": ["politics", "social", "activism", "movement"],
        }
        for cat, words in categories.items():
            if any(w in topic_lower for w in words):
                return cat
        return "other"

    def _forecast_trend(self, momentum: float, growth: float) -> str:
        if momentum > 0.7 and growth > 50:
            return "Rising rapidly — peak in 2-3 days"
        elif momentum > 0.5:
            return "Growing steadily — peak in 1 week"
        elif momentum > 0.3:
            return "Moderate growth — stable for now"
        else:
            return "Slow growth — unlikely to spike"

    # ── Content Similarity Analysis ────────────────────────────────────────

    def find_similar_content(
        self,
        content_id: str,
        content: dict,
        all_content: list[dict],
    ) -> ContentSimilarity:
        """Find similar content."""
        similar = []
        shared_elements = []

        body_lower = content.get("body", "").lower()
        words = set(body_lower.split())

        for other in all_content:
            if other.get("id") == content_id:
                continue

            other_words = set(other.get("body", "").lower().split())

            # Jaccard similarity
            overlap = len(words & other_words)
            similarity = overlap / max(1, len(words | other_words))

            if similarity > 0.2:
                shared = list(words & other_words)[:5]
                similar.append({
                    "id": other.get("id", ""),
                    "similarity": similarity,
                    "title": other.get("title", ""),
                    "engagement": other.get("engagement", 0),
                    "shared_words": shared,
                })

        # Find common elements across similar content
        if similar:
            all_shared = set()
            for s in similar:
                all_shared.update(s["shared_words"])
            shared_elements = list(all_shared)[:10]

        result = ContentSimilarity(
            content_id=content_id,
            similar=sorted(similar, key=lambda s: -s["similarity"])[:10],
            shared_elements=shared_elements,
            similarity_score=sum(s["similarity"] for s in similar) / max(1, len(similar)),
        )

        self._similarity[content_id] = result
        return result

    # ── Shareability Analysis ─────────────────────────────────────────────

    def analyze_shareability(
        self,
        content_id: str,
        content: dict,
    ) -> ShareabilityAnalysis:
        """Analyze content shareability."""
        body_lower = content.get("body", "").lower()

        # Emotional triggers
        emotional_triggers = []
        emotion_map = {
            "awe": ["amazing", "incredible", "wow"],
            "joy": ["love", "happy", "funny", "heartwarming"],
            "inspiration": ["motivating", "inspiring", "success"],
            "outrage": ["shocking", "unbelievable", "disgusting"],
            "empathy": ["understand", "feel", "relate"],
        }

        for emotion, words in emotion_map.items():
            if any(w in body_lower for w in words):
                emotional_triggers.append(emotion)

        # Share factors
        share_factors = []

        if "share" in body_lower or "retweet" in body_lower:
            share_factors.append("explicit share request")

        if any(w in body_lower for w in ["because", "the reason", "here's why"]):
            share_factors.append("explanatory content")

        if "you" in body_lower:
            share_factors.append("personal connection")

        if any(w in body_lower for w in ["shocking", "unbelievable", "mind-blowing"]):
            share_factors.append("surprise factor")

        # Calculate score
        score = 50.0
        score += len(emotional_triggers) * 10
        score += len(share_factors) * 5
        if content.get("has_visual", False):
            score += 15
        if self._has_hook(content):
            score += 10

        # Platform-specific shares
        platform = content.get("platform", "")
        shares_by_platform = {}

        for plat, base in [("twitter", 50), ("instagram", 30), ("facebook", 40), ("linkedin", 20)]:
            shares_by_platform[plat] = int(base * score / 50)

        # Optimal hook
        hook = content.get("title", "Untitled")[:80]

        recommendation = (
            "Strong shareability potential" if score > 70 else
            "Moderate shareability" if score > 50 else
            "Consider adding emotional triggers or share requests"
        )

        result = ShareabilityAnalysis(
            content_id=content_id,
            score=min(100, score),
            emotional_triggers=emotional_triggers,
            share_factors=share_factors,
            shares_by_platform=shares_by_platform,
            optimal_hook=hook,
            recommendation=recommendation,
        )

        return result

    # ── Optimal Post Timing ───────────────────────────────────────────────

    def get_optimal_timing(
        self,
        platform: str,
        audience_region: str = "global",
    ) -> PostTiming:
        """Get optimal posting times."""
        optimal_times = {
            "twitter": ["09:00", "12:00", "17:00", "20:00"],
            "instagram": ["11:00", "13:00", "19:00", "21:00"],
            "youtube": ["14:00", "16:00", "18:00", "20:00"],
            "tiktok": ["12:00", "15:00", "18:00", "21:00"],
            "linkedin": ["08:00", "10:00", "12:00", "16:00"],
            "facebook": ["10:00", "14:00", "18:00", "20:00"],
        }

        worst_times = {
            "twitter": ["03:00", "06:00", "14:00", "23:00"],
            "instagram": ["04:00", "08:00", "15:00", "02:00"],
            "youtube": ["06:00", "10:00", "03:00", "23:00"],
            "tiktok": ["06:00", "09:00", "02:00", "04:00"],
            "linkedin": ["02:00", "06:00", "20:00", "23:00"],
            "facebook": ["05:00", "09:00", "02:00", "23:00"],
        }

        times = optimal_times.get(platform, ["12:00", "17:00"])
        worst = worst_times.get(platform, ["03:00", "06:00"])

        rationale = f"Peak engagement for {platform} typically occurs during {audience_region} business hours"

        return PostTiming(
            platform=platform,
            best_times=times,
            worst_times=worst,
            confidence=0.7,
            rationale=rationale,
        )

    # ── Viral Lifecycle Prediction ────────────────────────────────────────

    def predict_viral_lifecycle(
        self,
        content_id: str,
        score: float,
        platform: str,
    ) -> ViralLifecycle:
        """Predict viral lifecycle."""
        phases = []

        # Lifecycle stages
        stages = [
            {"name": "seeding", "duration": 1, "growth": 0.2},
            {"name": "early_adoption", "duration": 3, "growth": 0.5},
            {"name": "viral_growth", "duration": 5, "growth": 1.0},
            {"name": "peak", "duration": 2, "growth": 0.3},
            {"name": "decay", "duration": 10, "growth": -0.5},
        ]

        total_shares = 0
        peak_shares = 0
        peak_time = 0
        now = time.time()

        for stage in stages:
            shares = int(score * stage["growth"] * 10)
            total_shares += shares
            peak_shares = max(peak_shares, shares)

            if stage["growth"] > 0 and shares > peak_shares:
                peak_time = now + stage["duration"] * 3600

            phases.append({
                "phase": stage["name"],
                "start_offset": sum(s["duration"] for s in stages[:stages.index(stage)]),
                "duration": stage["duration"],
                "shares": shares,
                "growth_rate": stage["growth"],
            })

        total_duration = sum(s["duration"] for s in stages)
        decay_rate = 0.3  # 30% daily decay

        result = ViralLifecycle(
            content_id=content_id,
            phases=phases,
            peak_time=peak_time,
            total_duration=total_duration,
            peak_shares=peak_shares,
            total_shares=total_shares,
            decay_rate=decay_rate,
        )

        self._lifecycles[content_id] = result
        return result

    # ── Viral Pattern Learning ────────────────────────────────────────────

    def learn_viral_pattern(
        self,
        description: str,
        common_elements: list[str],
        examples: list[str],
        success_count: int = 0,
        total_count: int = 0,
    ) -> ViralPattern:
        """Learn a viral pattern."""
        success_rate = success_count / max(1, total_count) if total_count > 0 else 0.0

        pattern = ViralPattern(
            pattern_id=hashlib.md5(
                f"pattern:{description}:{time.time()}".encode()
            ).hexdigest()[:12],
            description=description,
            common_elements=common_elements,
            success_rate=success_rate,
            examples=examples,
            learned_at=time.time(),
        )

        self._patterns.append(pattern)
        return pattern

    def get_top_patterns(self, count: int = 5) -> list[ViralPattern]:
        """Get top viral patterns."""
        return sorted(self._patterns, key=lambda p: -p.success_rate)[:count]


# ── API Routes ──────────────────────────────────────────────────────────────

predictor = ViralPredictor()


@router.post("/api/v1/viral/score")
async def score_viral_potential(payload: dict):
    """Score viral potential."""
    result = predictor.score_viral_potential(
        payload["content_id"],
        payload["content"],
    )
    return result.__dict__


@router.post("/api/v1/viral/trends")
async def detect_trends(payload: dict):
    """Detect trends."""
    trends = predictor.detect_trends(
        payload["posts"],
        payload.get("window_hours", 24),
    )
    return [t.__dict__ for t in trends]


@router.post("/api/v1/viral/similar")
async def find_similar(payload: dict):
    """Find similar content."""
    result = predictor.find_similar_content(
        payload["content_id"],
        payload["content"],
        payload["all_content"],
    )
    return result.__dict__


@router.post("/api/v1/viral/shareability")
async def analyze_shareability(payload: dict):
    """Analyze shareability."""
    result = predictor.analyze_shareability(
        payload["content_id"],
        payload["content"],
    )
    return result.__dict__


@router.get("/api/v1/viral/timing/{platform}")
async def get_optimal_timing(platform: str):
    """Get optimal timing."""
    timing = predictor.get_optimal_timing(platform)
    return timing.__dict__


@router.post("/api/v1/viral/lifecycle")
async def predict_lifecycle(payload: dict):
    """Predict viral lifecycle."""
    result = predictor.predict_viral_lifecycle(
        payload["content_id"],
        payload["score"],
        payload["platform"],
    )
    return result.__dict__


@router.get("/api/v1/viral/patterns")
async def get_patterns(count: int = 5):
    """Get top viral patterns."""
    patterns = predictor.get_top_patterns(count)
    return [p.__dict__ for p in patterns]


@router.post("/api/v1/viral/learn")
async def learn_pattern(payload: dict):
    """Learn a viral pattern."""
    pattern = predictor.learn_viral_pattern(
        description=payload["description"],
        common_elements=payload["common_elements"],
        examples=payload["examples"],
        success_count=payload.get("success_count", 0),
        total_count=payload.get("total_count", 0),
    )
    return pattern.__dict__
