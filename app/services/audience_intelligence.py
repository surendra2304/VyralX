"""
VyralX/app/services/audience_intelligence.py — VyralX Audience Intelligence Engine.

Extends VyralX's capabilities with:
1. Audience Segmentation: segment audience by behavior and demographics
2. Demographics Analysis: analyze audience demographics
3. Interest Profiling: build interest profiles for audiences
4. Audience Overlap: find overlap between audiences
5. Lookalike Audiences: find similar audiences
6. Audience Growth Prediction: predict audience growth patterns
7. Engagement Predictor: predict which content will engage specific segments
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AudienceSegment:
    """An audience segment."""
    segment_id: str
    name: str
    size: int
    characteristics: dict[str, Any] = field(default_factory=dict)
    engagement_score: float = 0.0
    growth_rate: float = 0.0
    value_score: float = 0.0


@dataclass
class DemographicProfile:
    """Demographic profile."""
    age_range: str = ""
    gender: str = ""
    location: str = ""
    language: str = ""
    device_type: str = ""
    income_level: str = ""
    education_level: str = ""


@dataclass
class InterestProfile:
    """Interest profile."""
    interests: dict[str, float] = field(default_factory=dict)
    top_interests: list[str] = field(default_factory=list)
    content_preferences: dict[str, str] = field(default_factory=dict)
    platform_usage: dict[str, float] = field(default_factory=dict)


@dataclass
class AudienceOverlap:
    """Overlap between two audiences."""
    audience_a: str
    audience_b: str
    overlap_percentage: float
    common_interests: list[str]
    unique_to_a: list[str]
    unique_to_b: list[str]


@dataclass
class LookalikeAudience:
    """A lookalike audience."""
    source_audience: str
    lookalike_id: str
    similarity_score: float
    estimated_size: int
    key_attributes: list[str]
    predicted_engagement: float


@dataclass
class EngagementPrediction:
    """Predict engagement for a segment."""
    segment_id: str
    content_type: str
    predicted_engagement: float
    predicted_views: int
    predicted_watch_time: float
    confidence: float
    recommendations: list[str]


class AudienceIntelligence:
    """Audience intelligence engine."""

    def __init__(self):
        self._segments: dict[str, AudienceSegment] = {}
        self._demographics: dict[str, DemographicProfile] = {}
        self._interests: dict[str, InterestProfile] = {}
        self._overlaps: list[AudienceOverlap] = []
        self._lookalikes: dict[str, LookalikeAudience] = {}
        self._engagement_predictions: dict[str, EngagementPrediction] = {}

    # ── Audience Segmentation ───────────────────────────────────────────────

    def segment_audience(
        self,
        audience_id: str,
        members: list[dict],
    ) -> list[AudienceSegment]:
        """Segment an audience by behavior and demographics."""
        segments = []

        # Group by activity level
        low_activity = []
        medium_activity = []
        high_activity = []

        for member in members:
            activity = member.get("activity_score", 0.0)
            if activity > 0.7:
                high_activity.append(member)
            elif activity > 0.3:
                medium_activity.append(member)
            else:
                low_activity.append(member)

        if high_activity:
            segments.append(AudienceSegment(
                segment_id=f"seg_high_{audience_id}",
                name="Highly Engaged",
                size=len(high_activity),
                characteristics={"activity": "high", "avg_watch_time": 0.8},
                engagement_score=0.9,
                growth_rate=0.15,
                value_score=0.9,
            ))

        if medium_activity:
            segments.append(AudienceSegment(
                segment_id=f"seg_med_{audience_id}",
                name="Moderately Engaged",
                size=len(medium_activity),
                characteristics={"activity": "medium", "avg_watch_time": 0.5},
                engagement_score=0.6,
                growth_rate=0.08,
                value_score=0.6,
            ))

        if low_activity:
            segments.append(AudienceSegment(
                segment_id=f"seg_low_{audience_id}",
                name="Low Engagement",
                size=len(low_activity),
                characteristics={"activity": "low", "avg_watch_time": 0.2},
                engagement_score=0.3,
                growth_rate=-0.05,
                value_score=0.2,
            ))

        for seg in segments:
            self._segments[seg.segment_id] = seg

        return segments

    # ── Demographics Analysis ───────────────────────────────────────────────

    def analyze_demographics(
        self,
        audience_id: str,
        members: list[dict],
    ) -> DemographicProfile:
        """Analyze audience demographics."""
        profile = DemographicProfile()

        # Age distribution
        ages = [m.get("age", 25) for m in members]
        if ages:
            avg_age = sum(ages) / len(ages)
            if avg_age < 18:
                profile.age_range = "13-17"
            elif avg_age < 25:
                profile.age_range = "18-24"
            elif avg_age < 35:
                profile.age_range = "25-34"
            elif avg_age < 45:
                profile.age_range = "35-44"
            else:
                profile.age_range = "45+"

        # Gender
        genders = [m.get("gender", "") for m in members]
        if genders:
            male = sum(1 for g in genders if g.lower() == "male")
            female = sum(1 for g in genders if g.lower() == "female")
            profile.gender = "male" if male > female else "female" if female > male else "mixed"

        # Location
        locations = [m.get("location", "") for m in members]
        if locations:
            from collections import Counter
            most_common = Counter(locations).most_common(1)
            if most_common:
                profile.location = most_common[0][0]

        # Language
        langs = [m.get("language", "en") for m in members]
        if langs:
            from collections import Counter
            most_common = Counter(langs).most_common(1)
            if most_common:
                profile.language = most_common[0][0]

        # Device
        devices = [m.get("device", "desktop") for m in members]
        if devices:
            from collections import Counter
            most_common = Counter(devices).most_common(1)
            if most_common:
                profile.device_type = most_common[0][0]

        self._demographics[audience_id] = profile
        return profile

    # ── Interest Profiling ─────────────────────────────────────────────────

    def profile_interests(
        self,
        audience_id: str,
        view_history: list[dict],
    ) -> InterestProfile:
        """Build interest profile from view history."""
        profile = InterestProfile()

        # Count interest frequency
        interest_freq: dict[str, int] = {}
        for view in view_history:
            for tag in view.get("tags", []):
                interest_freq[tag] = interest_freq.get(tag, 0) + 1

        # Calculate interest scores
        total_views = len(view_history)
        for interest, count in interest_freq.items():
            profile.interests[interest] = count / max(1, total_views)

        # Sort by score
        profile.top_interests = sorted(
            profile.interests,
            key=profile.interests.get,
            reverse=True
        )[:10]

        # Content preferences
        content_types: dict[str, int] = {}
        for view in view_history:
            ct = view.get("content_type", "unknown")
            content_types[ct] = content_types.get(ct, 0) + 1

        for ct, count in content_types.items():
            profile.content_preferences[ct] = count / max(1, total_views)

        self._interests[audience_id] = profile
        return profile

    # ── Audience Overlap ────────────────────────────────────────────────────

    def calculate_overlap(
        self,
        audience_a_id: str,
        audience_b_id: str,
    ) -> AudienceOverlap:
        """Calculate overlap between two audiences."""
        interests_a = self._interests.get(audience_a_id, InterestProfile())
        interests_b = self._interests.get(audience_b_id, InterestProfile())

        all_interests = set(interests_a.interests.keys()) | set(interests_b.interests.keys())

        common = set(interests_a.interests.keys()) & set(interests_b.interests.keys())
        unique_a = set(interests_a.interests.keys()) - common
        unique_b = set(interests_b.interests.keys()) - common

        overlap_pct = len(common) / max(1, len(all_interests))

        overlap = AudienceOverlap(
            audience_a=audience_a_id,
            audience_b=audience_b_id,
            overlap_percentage=overlap_pct,
            common_interests=list(common),
            unique_to_a=list(unique_a),
            unique_to_b=list(unique_b),
        )

        self._overlaps.append(overlap)
        return overlap

    # ── Lookalike Audiences ─────────────────────────────────────────────────

    def create_lookalike(
        self,
        source_audience_id: str,
        target_size: int = 1000,
    ) -> LookalikeAudience:
        """Create a lookalike audience."""
        profile = self._interests.get(source_audience_id, InterestProfile())

        lookalike = LookalikeAudience(
            source_audience=source_audience_id,
            lookalike_id=f"lookalike_{source_audience_id}_{int(time.time())}",
            similarity_score=0.75,
            estimated_size=target_size,
            key_attributes=profile.top_interests[:5],
            predicted_engagement=profile.interests.get(profile.top_interests[0], 0.5) if profile.top_interests else 0.5,
        )

        self._lookalikes[lookalike.lookalike_id] = lookalike
        return lookalike

    # ── Engagement Predictor ────────────────────────────────────────────────

    def predict_engagement(
        self,
        segment_id: str,
        content_type: str,
        content_length: float = 10.0,
    ) -> EngagementPrediction:
        """Predict engagement for a segment."""
        segment = self._segments.get(segment_id)
        if not segment:
            return EngagementPrediction(
                segment_id=segment_id,
                content_type=content_type,
                predicted_engagement=0.0,
                predicted_views=0,
                predicted_watch_time=0.0,
                confidence=0.0,
                recommendations=["Segment not found"],
            )

        # Base engagement from segment
        base_engagement = segment.engagement_score

        # Adjust for content type
        type_factors = {
            "tutorial": 1.2,
            "review": 1.1,
            "vlog": 0.9,
            "entertainment": 1.0,
            "education": 1.15,
        }
        content_factor = type_factors.get(content_type, 1.0)

        # Adjust for length
        length_factor = max(0.5, 1.0 - content_length / 60.0)

        predicted_engagement = base_engagement * content_factor * length_factor

        # Predict views
        predicted_views = int(segment.size * predicted_engagement * 0.1)

        # Predict watch time
        predicted_watch_time = predicted_engagement * content_length

        # Confidence
        confidence = min(0.85, segment.engagement_score * 0.5 + 0.3)

        # Recommendations
        recommendations = []
        if predicted_engagement < 0.3:
            recommendations.append("Consider shorter content or more engaging format")
        elif predicted_engagement > 0.7:
            recommendations.append("This segment will love this content - promote it!")

        if content_length > 20:
            recommendations.append("Consider adding chapters for longer content")

        prediction = EngagementPrediction(
            segment_id=segment_id,
            content_type=content_type,
            predicted_engagement=predicted_engagement,
            predicted_views=predicted_views,
            predicted_watch_time=predicted_watch_time,
            confidence=confidence,
            recommendations=recommendations,
        )

        self._engagement_predictions[f"{segment_id}_{content_type}"] = prediction
        return prediction

    # ── Audience Growth Prediction ───────────────────────────────────────────

    def predict_growth(
        self,
        audience_id: str,
        historical_sizes: list[int],
    ) -> dict[str, Any]:
        """Predict audience growth."""
        if len(historical_sizes) < 2:
            return {"prediction": "insufficient_data", "confidence": 0.0}

        # Calculate growth rate
        growth_rate = (
            (historical_sizes[-1] - historical_sizes[0]) /
            max(1, historical_sizes[0]) / max(1, len(historical_sizes))
        )

        # Project future
        projected = historical_sizes[-1] * (1 + growth_rate) ** 4  # 4 periods ahead

        # Confidence
        confidence = min(0.8, abs(growth_rate) * 5)

        return {
            "audience_id": audience_id,
            "current_size": historical_sizes[-1],
            "projected_size": int(projected),
            "growth_rate": growth_rate,
            "confidence": confidence,
            "recommendation": (
                "Audience is growing - invest in expansion" if growth_rate > 0.05 else
                "Audience is declining - investigate causes" if growth_rate < -0.05 else
                "Audience is stable"
            ),
        }

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_audience_report(self) -> dict[str, Any]:
        """Generate an audience intelligence report."""
        return {
            "total_segments": len(self._segments),
            "total_demographics": len(self._demographics),
            "total_interest_profiles": len(self._interests),
            "total_overlaps": len(self._overlaps),
            "total_lookalikes": len(self._lookalikes),
            "engagement_predictions": len(self._engagement_predictions),
        }
