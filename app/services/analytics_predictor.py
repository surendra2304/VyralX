"""
VyralX/app/services/analytics_predictor.py — VyralX Analytics Predictor.

Extends VyralX's capabilities with:
1. View Count Prediction: predict future view counts using growth models
2. Audience Retention Forecasting: predict audience retention over time
3. Video Performance Scoring: score videos before publishing
4. Channel Growth Modeling: model channel growth trajectories
5. Competitor Analysis: analyze competitor channels and content
6. Trend Detection: detect emerging trends in the niche
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ViewPrediction:
    """Predicted view count for a video."""
    title: str
    predicted_views: int
    predicted_ctr: float
    growth_rate: float
    confidence: float
    time_to_peak: float  # hours


@dataclass
class RetentionForecast:
    """Retention forecast for a video."""
    title: str
    predicted_retention_curve: list[float]
    estimated_watch_hours: float
    drop_off_points: list[float]  # timestamps where big drops happen
    engagement_score: float


@dataclass
class ChannelGrowthModel:
    """Channel growth trajectory model."""
    channel_name: str
    current_subscribers: int
    predicted_subscribers: int
    growth_rate: float
    projected_months: int
    confidence: float
    risk_factors: list[str]


@dataclass
class CompetitorInsight:
    """Insights from competitor analysis."""
    competitor_name: str
    total_videos: int
    avg_views: int
    upload_frequency: float  # videos per week
    top_topics: list[str]
    engagement_rate: float
    subscriber_growth: float
    gap_analysis: str


class AnalyticsPredictor:
    """Predictive analytics for YouTube channel optimization."""

    def __init__(self):
        self._predictions: list[ViewPrediction] = []
        self._forecasts: list[RetentionForecast] = []
        self._growth_models: dict[str, ChannelGrowthModel] = {}
        self._competitor_insights: dict[str, CompetitorInsight] = {}

    # ── View Count Prediction ──────────────────────────────────────────────

    def predict_views(
        self,
        title: str,
        description: str,
        tags: list[str],
        channel_subscribers: int,
        niche: str = "",
        competitor_avg_views: int = 10000,
    ) -> ViewPrediction:
        """Predict view count for a video before publishing."""
        # Base views from channel size
        base_views = channel_subscribers * 0.1  # 10% of subscribers watch

        # Title quality factor
        title_factor = 1.0
        if len(title) < 30:
            title_factor *= 0.9  # Short titles underperform
        if len(title) > 80:
            title_factor *= 0.85  # Too long
        if any(w in title.lower() for w in ["how", "tutorial", "guide", "best", "review"]):
            title_factor *= 1.2  # How-to titles perform well
        if any(w in title.lower() for w in ["vlog", "day in the life"]):
            title_factor *= 0.8  # Vlogs underperform

        # Description quality
        desc_factor = 1.0
        if len(description) > 200:
            desc_factor *= 1.1
        if len(description) < 50:
            desc_factor *= 0.9

        # Tag quality
        tag_factor = 1.0
        if len(tags) > 10:
            tag_factor *= 0.95
        if len(tags) < 3:
            tag_factor *= 0.8
        if niche and any(niche.lower() in t.lower() for t in tags):
            tag_factor *= 1.15

        # Niche factor
        niche_factor = 1.0
        high_demand_niches = {"technology", "gaming", "finance", "education", "howto"}
        if niche.lower() in high_demand_niches:
            niche_factor *= 1.3
        elif niche.lower() in {"lifestyle", "beauty", "fashion"}:
            niche_factor *= 1.1

        # Calculate predicted views
        predicted = base_views * title_factor * desc_factor * tag_factor * niche_factor

        # CTR prediction
        predicted_ctr = min(0.15, 0.05 * title_factor * niche_factor)

        # Growth rate (views per day in first week)
        growth_rate = predicted * 0.3  # 30% of views in first week

        # Time to peak
        time_to_peak = 48.0 if niche_factor > 1.2 else 72.0

        # Confidence
        confidence = min(0.9, 0.5 + (len(title) / 100.0) + (len(tags) / 20.0))

        prediction = ViewPrediction(
            title=title,
            predicted_views=int(predicted),
            predicted_ctr=predicted_ctr,
            growth_rate=growth_rate,
            confidence=confidence,
            time_to_peak=time_to_peak,
        )

        self._predictions.append(prediction)
        return prediction

    # ── Retention Forecasting ───────────────────────────────────────────────

    def forecast_retention(
        self,
        title: str,
        video_length: float,  # seconds
        estimated_quality: float = 0.5,  # 0-1
        estimated_hook_strength: float = 0.5,  # 0-1
    ) -> RetentionForecast:
        """Forecast retention curve for a video."""
        # Generate predicted retention curve
        segments = min(50, int(video_length / 5))  # 5-second segments
        curve = []

        # Initial retention (first 30 seconds)
        initial_retention = 0.7 + estimated_hook_strength * 0.2
        curve.append(initial_retention)

        # Decline rate based on quality
        decline_rate = 0.02 + (1.0 - estimated_quality) * 0.03

        for i in range(1, segments):
            # Slower decline for high quality
            segment_decline = decline_rate * (0.5 + (1.0 - estimated_quality) * 0.5)

            # Add some randomness
            import random
            noise = random.uniform(-0.01, 0.01)

            retention = curve[-1] - segment_decline + noise
            retention = max(0.1, min(1.0, retention))
            curve.append(retention)

        # Estimate watch hours
        watch_hours = sum(curve) * (video_length / 3600.0) * 100  # 100 = estimated viewers

        # Find drop-off points (big declines)
        drop_offs = []
        for i in range(1, len(curve)):
            if curve[i-1] - curve[i] > 0.05:
                drop_offs.append(i * 5)  # Convert to seconds

        # Engagement score
        engagement_score = sum(curve) / len(curve) * estimated_quality

        forecast = RetentionForecast(
            title=title,
            predicted_retention_curve=curve,
            estimated_watch_hours=watch_hours,
            drop_off_points=drop_offs,
            engagement_score=engagement_score,
        )

        self._forecasts.append(forecast)
        return forecast

    # ── Video Performance Scoring ───────────────────────────────────────────

    def score_video(
        self,
        title: str,
        description: str,
        tags: list[str],
        thumbnail_description: str,
        video_length: float,
        channel_subscribers: int,
    ) -> dict[str, Any]:
        """Score a video's likely performance before publishing."""
        prediction = self.predict_views(
            title=title,
            description=description,
            tags=tags,
            channel_subscribers=channel_subscribers,
        )

        forecast = self.forecast_retention(
            title=title,
            video_length=video_length,
        )

        # Overall score
        title_score = min(1.0, len(title) / 60.0)
        desc_score = min(1.0, len(description) / 300.0)
        tag_score = min(1.0, len(tags) / 10.0)
        retention_score = forecast.engagement_score

        overall_score = (
            title_score * 0.25 +
            desc_score * 0.15 +
            tag_score * 0.15 +
            retention_score * 0.35 +
            prediction.confidence * 0.10
        )

        return {
            "title": title,
            "overall_score": overall_score * 100,
            "predicted_views": prediction.predicted_views,
            "predicted_ctr": prediction.predicted_ctr,
            "retention_score": retention_score,
            "title_score": title_score,
            "description_score": desc_score,
            "tag_score": tag_score,
            "recommendation": (
                "Publish immediately" if overall_score > 0.7 else
                "Optimize and republish" if overall_score > 0.4 else
                "Significant improvements needed"
            ),
        }

    # ── Channel Growth Modeling ──────────────────────────────────────────────

    def model_channel_growth(
        self,
        channel_name: str,
        current_subscribers: int,
        upload_frequency: float,  # videos per week
        avg_views: int,
        engagement_rate: float,
        months: int = 6,
    ) -> ChannelGrowthModel:
        """Model channel growth trajectory."""
        # Growth rate based on engagement and upload frequency
        base_growth = 0.05  # 5% monthly base growth

        # Engagement boost
        engagement_boost = engagement_rate * 2.0  # 0-2
        upload_boost = min(0.5, upload_frequency * 0.1)  # More uploads = more growth

        monthly_growth = base_growth + engagement_boost * 0.02 + upload_boost

        # Cap growth
        monthly_growth = min(0.3, monthly_growth)

        # Predict subscribers
        predicted = current_subscribers * (1.0 + monthly_growth) ** months

        # Risk factors
        risk_factors = []
        if engagement_rate < 0.03:
            risk_factors.append("Low engagement rate may slow growth")
        if upload_frequency < 1.0:
            risk_factors.append("Low upload frequency limits growth")
        if avg_views < 1000:
            risk_factors.append("Low average views indicate content issues")

        # Confidence based on data quality
        confidence = min(0.85, 0.4 + engagement_rate * 5 + upload_frequency * 0.1)

        model = ChannelGrowthModel(
            channel_name=channel_name,
            current_subscribers=current_subscribers,
            predicted_subscribers=int(predicted),
            growth_rate=monthly_growth,
            projected_months=months,
            confidence=confidence,
            risk_factors=risk_factors,
        )

        self._growth_models[channel_name] = model
        return model

    # ── Competitor Analysis ──────────────────────────────────────────────────

    def analyze_competitor(
        self,
        competitor_name: str,
        total_videos: int,
        avg_views: int,
        upload_frequency: float,
        top_topics: list[str],
        engagement_rate: float,
        subscriber_growth: float,
        your_channel_subscribers: int = 0,
    ) -> CompetitorInsight:
        """Analyze a competitor channel and identify gaps."""
        # Gap analysis
        gaps = []

        if engagement_rate > 0.05:
            gaps.append(f"Competitor has high engagement ({engagement_rate:.1%}). Focus on engagement boosting.")

        if upload_frequency > 2.0:
            gaps.append(f"Competitor uploads {upload_frequency}x/week. Consider increasing frequency.")

        if avg_views > 10000:
            gaps.append(f"Competitor averages {avg_views} views. Analyze their content strategy.")

        # Identify topic gaps
        competitor_topics = set(top_topics)
        # (In production, compare with your channel's topics)
        gap_analysis = "; ".join(gaps) if gaps else "No significant gaps detected"

        insight = CompetitorInsight(
            competitor_name=competitor_name,
            total_videos=total_videos,
            avg_views=avg_views,
            upload_frequency=upload_frequency,
            top_topics=top_topics,
            engagement_rate=engagement_rate,
            subscriber_growth=subscriber_growth,
            gap_analysis=gap_analysis,
        )

        self._competitor_insights[competitor_name] = insight
        return insight

    # ── Trend Detection ─────────────────────────────────────────────────────

    def detect_trends(
        self,
        search_results: list[dict],
        niche: str = "",
    ) -> list[dict]:
        """Detect emerging trends in search results."""
        trends = []

        # Analyze search results for patterns
        topic_frequency: dict[str, int] = {}
        title_keywords: dict[str, int] = {}

        for result in search_results:
            title = result.get("title", "")
            views = result.get("views", 0)

            # Count topics
            for word in title.split():
                if len(word) > 3:
                    title_keywords[word.lower()] = title_keywords.get(word.lower(), 0) + 1

        # Find trending keywords
        sorted_keywords = sorted(
            title_keywords.items(),
            key=lambda x: -x[1]
        )

        for keyword, count in sorted_keywords[:10]:
            if count >= 3:  # Must appear at least 3 times
                trends.append({
                    "keyword": keyword,
                    "frequency": count,
                    "trend_score": count * 0.2,
                    "suggestion": f"Consider creating content about '{keyword}'",
                })

        return trends

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_analytics_report(self) -> dict[str, Any]:
        """Generate an analytics report."""
        return {
            "total_predictions": len(self._predictions),
            "total_forecasts": len(self._forecasts),
            "growth_models": len(self._growth_models),
            "competitor_insights": len(self._competitor_insights),
            "avg_predicted_views": (
                sum(p.predicted_views for p in self._predictions) / len(self._predictions)
                if self._predictions else 0
            ),
        }
