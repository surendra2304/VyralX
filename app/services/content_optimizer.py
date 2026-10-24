"""
app/services/content_optimizer.py — VyralX Content Optimization Engine.

Optimizes video content for maximum engagement:
1. Title Optimization: A/B testing framework for titles
2. Description Optimization: SEO-optimized descriptions with CTAs
3. Thumbnail Optimization: Visual analysis for click-through rate
4. Tag Optimization: Keyword-based tag selection
5. Hook Optimization: First 30 seconds hook analysis
6. Retention Analysis: Predictive retention curve modeling
7. Publishing Time Optimization: Best time to publish based on analytics
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("vyralx.optimizer")


@dataclass
class TitleCandidate:
    """A title candidate for A/B testing."""
    title: str
    predicted_ctr: float = 0.0
    character_count: int = 0
    emotion_score: float = 0.0
    keyword_score: float = 0.0

    def __post_init__(self):
        self.character_count = len(self.title)

    def calculate_score(self, keywords: list[str]) -> float:
        """Calculate a composite score for the title."""
        # CTR prediction (base 0.05, adjusted by factors)
        ctr_score = min(0.15, 0.05 + self.predicted_ctr * 0.1)

        # Character count optimal (60-80 chars is ideal for YouTube)
        char_score = 1.0 if 60 <= self.character_count <= 80 else 0.7

        # Emotion score (higher is better for engagement)
        emotion_score = min(1.0, self.emotion_score * 2)

        # Keyword score
        keyword_score = min(1.0, self.keyword_score * 2)

        return (ctr_score * 0.3 + char_score * 0.2 +
                emotion_score * 0.25 + keyword_score * 0.25)


@dataclass
class DescriptionOptimization:
    """Optimized video description."""
    hook: str
    body: str
    cta: str
    keywords: list[str]
    hashtags: list[str]
    timestamps: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


@dataclass
class ThumbnailAnalysis:
    """Analysis of thumbnail effectiveness."""
    brightness_score: float = 0.5
    contrast_score: float = 0.5
    emotion_score: float = 0.5
    face_score: float = 0.5
    text_score: float = 0.5
    predicted_ctr: float = 0.05


class ContentOptimizer:
    """Optimizes video content for maximum engagement."""

    EMOTION_KEYWORDS = {
        "positive": {"amazing", "incredible", "best", "mind-blowing", "awesome", "unbelievable", "crazy", "insane"},
        "negative": {"terrible", "worst", "disgusting", "horrible", "awful", "broken", "fails"},
        "curiosity": {"why", "how", "what", "secret", "truth", "shocking", "revealed", "exposed"},
        "urgency": {"now", "today", "this week", "limited", "urgent", "breaking", "update"},
    }

    def __init__(self):
        self.ab_test_results: dict[str, dict] = {}
        self.optimization_history: list[dict] = []

    async def optimize_title(
        self,
        topic: str,
        keywords: list[str],
        candidates: list[str] | None = None,
    ) -> TitleCandidate:
        """Optimize a title for maximum click-through rate."""
        if candidates:
            # Evaluate provided candidates
            best = None
            best_score = 0.0

            for candidate in candidates:
                scored = self._score_title(candidate, keywords)
                if scored.calculate_score(keywords) > best_score:
                    best = scored
                    best_score = scored.calculate_score(keywords)

            return best or self._generate_title(topic, keywords)

        # Generate title candidates
        return self._generate_title(topic, keywords)

    def _generate_title(self, topic: str, keywords: list[str]) -> TitleCandidate:
        """Generate an optimized title."""
        # Template-based generation
        templates = [
            f"This {topic} Will Change Everything",
            f"The Truth About {topic} Nobody Told You",
            f"Why {topic} Is More Important Than You Think",
            f"{topic}: The Ultimate Guide (2026)",
            f"I Tried {topic} for 30 Days — Here's What Happened",
            f"Stop Ignoring {topic} — Here's Why",
            f"{topic} Explained in 60 Seconds",
        ]

        best = None
        best_score = 0.0

        for template in templates:
            candidate = TitleCandidate(title=template)
            candidate.predicted_ctr = 0.05 + len(keywords) * 0.01
            candidate.keyword_score = self._keyword_match_score(template, keywords)
            candidate.emotion_score = self._emotion_score(template)

            score = candidate.calculate_score(keywords)
            if score > best_score:
                best = candidate
                best_score = score

        return best or TitleCandidate(title=topic)

    def _score_title(self, title: str, keywords: list[str]) -> TitleCandidate:
        """Score an existing title."""
        candidate = TitleCandidate(title=title)
        candidate.predicted_ctr = 0.05 + len(keywords) * 0.01
        candidate.keyword_score = self._keyword_match_score(title, keywords)
        candidate.emotion_score = self._emotion_score(title)
        return candidate

    def _keyword_match_score(self, text: str, keywords: list[str]) -> float:
        """Calculate keyword match score."""
        text_lower = text.lower()
        matches = sum(1 for kw in keywords if kw.lower() in text_lower)
        return matches / len(keywords) if keywords else 0.0

    def _emotion_score(self, text: str) -> float:
        """Calculate emotion score based on keywords."""
        text_lower = text.lower()
        score = 0.0

        for emotion, keywords in self.EMOTION_KEYWORDS.items():
            matches = sum(1 for kw in keywords if kw in text_lower)
            if emotion == "positive":
                score += matches * 0.3
            elif emotion == "curiosity":
                score += matches * 0.25
            elif emotion == "urgency":
                score += matches * 0.2
            elif emotion == "negative":
                score += matches * 0.15  # Negative emotions still drive clicks

        return min(1.0, score)

    async def optimize_description(
        self,
        topic: str,
        video_content: str,
        keywords: list[str],
    ) -> DescriptionOptimization:
        """Optimize video description for SEO and engagement."""
        hook = self._generate_hook(topic)
        body = self._generate_body(video_content, keywords)
        cta = self._generate_cta()

        return DescriptionOptimization(
            hook=hook,
            body=body,
            cta=cta,
            keywords=keywords,
            hashtags=[f"#{kw.replace(' ', '')}" for kw in keywords[:5]],
        )

    def _generate_hook(self, topic: str) -> str:
        """Generate an engaging hook for the description."""
        return f"In this video, we dive deep into {topic}. " \
               f"You won't want to miss this!"

    def _generate_body(self, content: str, keywords: list[str]) -> str:
        """Generate the body of the description."""
        body = f"\n\n{content[:500]}\n\n"
        body += "Key points covered:\n"
        body += "\n".join(f"- {kw}" for kw in keywords[:5])
        return body

    def _generate_cta(self) -> str:
        """Generate a call-to-action."""
        return "\n\n💡 If you found this helpful, consider subscribing for more content!"

    def analyze_thumbnail(
        self,
        image_path: str | None = None,
    ) -> ThumbnailAnalysis:
        """Analyze thumbnail effectiveness."""
        # In production, this would use image analysis
        # For now, return default analysis
        return ThumbnailAnalysis(
            brightness_score=0.6,
            contrast_score=0.7,
            emotion_score=0.5,
            face_score=0.4,
            text_score=0.6,
            predicted_ctr=0.08,
        )

    def optimize_tags(
        self,
        topic: str,
        video_content: str,
        max_tags: int = 10,
    ) -> list[str]:
        """Optimize tags for SEO."""
        # Extract keywords from content
        words = re.findall(r'[a-zA-Z]+', (topic + " " + video_content).lower())
        word_freq = {}
        for word in words:
            if len(word) > 3:
                word_freq[word] = word_freq.get(word, 0) + 1

        # Sort by frequency
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)

        # Take top tags
        tags = [word for word, _ in sorted_words[:max_tags]]

        # Add topic-specific tags
        tags.insert(0, topic.replace(" ", ""))

        return tags[:max_tags]

    def predict_retention_curve(
        self,
        topic: str,
        video_length_seconds: int,
    ) -> dict[str, float]:
        """Predict viewer retention curve."""
        # Model retention as exponential decay
        # Stronger hooks and better content maintain higher retention

        hook_strength = self._emotion_score(topic)
        base_retention = 0.7  # 70% at 1 minute

        # Retention at various time points
        curve = {}
        for time_pct in [0.25, 0.5, 0.75, 1.0]:
            time_seconds = video_length_seconds * time_pct
            retention = base_retention * (1 - time_pct * 0.3) * (0.8 + hook_strength * 0.2)
            curve[f"{time_pct:.2f}"] = retention

        return curve

    def suggest_publish_time(
        self,
        audience_timezone: str = "UTC",
        historical_data: list[dict] | None = None,
    ) -> str:
        """Suggest optimal publish time based on analytics."""
        # Default: weekday evenings 6-8 PM
        # In production, analyze historical engagement data

        if historical_data:
            # Analyze when engagement was highest
            best_hour = self._analyze_best_hour(historical_data)
            return f"Weekday at {best_hour}:00 {audience_timezone}"

        return "Weekday at 18:00 UTC"

    def _analyze_best_hour(self, data: list[dict]) -> int:
        """Analyze historical data for best publishing hour."""
        hour_engagement: dict[int, list[float]] = {}

        for entry in data:
            hour = entry.get("hour", 18)
            engagement = entry.get("engagement", 0.5)
            hour_engagement.setdefault(hour, []).append(engagement)

        best_hour = 18
        best_score = 0.0

        for hour, engagements in hour_engagement.items():
            avg_engagement = sum(engagements) / len(engagements)
            if avg_engagement > best_score:
                best_score = avg_engagement
                best_hour = hour

        return best_hour

    async def run_ab_test(
        self,
        test_id: str,
        variants: list[str],
        metric: str = "ctr",
    ) -> dict[str, Any]:
        """Run an A/B test on content variants."""
        logger.info(f"Running A/B test: {test_id} with {len(variants)} variants")

        # In production, this would run the test over time
        # For now, return simulated results
        results = {}
        for i, variant in enumerate(variants):
            score = 0.05 + i * 0.01 + len(variant) * 0.001
            results[variant[:30]] = score

        self.ab_test_results[test_id] = results
        return results

    def get_optimization_report(self) -> dict[str, Any]:
        """Generate an optimization report."""
        return {
            "ab_tests": self.ab_test_results,
            "history": self.optimization_history,
            "total_optimizations": len(self.optimization_history),
        }


# Module-level singleton
content_optimizer = ContentOptimizer()
