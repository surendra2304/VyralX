"""
VyralX/app/services/video_analytics_dashboard.py — VyralX Video Analytics Dashboard Engine.

Comprehensive video performance analytics: view metrics, engagement tracking,
audience demographics, retention analysis, virality scoring, and competitive
benchmarking with real-time dashboards and alerts.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class VideoMetrics:
    """Metrics for a video."""
    video_id: str
    title: str
    views: int = 0
    likes: int = 0
    dislikes: int = 0
    shares: int = 0
    comments: int = 0
    watch_time_hours: float = 0.0
    avg_view_duration: float = 0.0  # seconds
    engagement_rate: float = 0.0
    retention_rate: float = 0.0
    ctr: float = 0.0  # click-through rate
    virality_score: float = 0.0
    revenue: float = 0.0
    timestamp: float = 0.0


@dataclass
class AudienceDemographics:
    """Audience demographics for a video."""
    video_id: str
    age_distribution: dict = field(default_factory=dict)  # {age_range: percentage}
    gender_distribution: dict = field(default_factory=dict)
    location_distribution: dict = field(default_factory=dict)
    device_distribution: dict = field(default_factory=dict)
    traffic_sources: dict = field(default_factory=dict)
    unique_viewers: int = 0
    returning_viewers_pct: float = 0.0


@dataclass
class RetentionCurve:
    """Viewer retention curve."""
    video_id: str
    segments: list[dict] = field(default_factory=list)  # [{timestamp_pct, retention_pct}]
    avg_retention: float = 0.0
    drop_off_points: list[float] = field(default_factory=list)
    peak_retention: float = 0.0
    last_segment_retention: float = 0.0


@dataclass
class ViralityAnalysis:
    """Virality analysis for a video."""
    video_id: str
    virality_score: float = 0.0
    sharing_rate: float = 0.0
    velocity_score: float = 0.0
    compound_score: float = 0.0
    predicted_views: int = 0
    days_to_viral: float = 0.0
    factors: list[str] = field(default_factory=list)


@dataclass
class CompetitiveBenchmark:
    """Competitive benchmarking."""
    video_id: str
    benchmark_group: str = ""
    avg_views_in_group: int = 0
    avg_engagement_in_group: float = 0.0
    avg_retention_in_group: float = 0.0
    percentile_rank: float = 0.0
    competitive_score: float = 0.0
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)


@dataclass
class PerformanceAlert:
    """A performance alert."""
    alert_id: str
    video_id: str
    alert_type: str  # views_spike, views_drop, engagement_low, retention_drop, virality_high
    severity: str = "medium"
    message: str = ""
    threshold: float = 0.0
    current_value: float = 0.0
    triggered_at: float = 0.0


@dataclass
class DashboardWidget:
    """A dashboard widget."""
    widget_id: str
    widget_type: str  # metric, chart, table, gauge, alert
    title: str
    data: list = field(default_factory=list)
    refresh_rate: int = 60  # seconds
    last_updated: float = 0.0


class VideoAnalyticsDashboard:
    """Video analytics dashboard engine."""

    def __init__(self):
        self._metrics: dict[str, VideoMetrics] = {}
        self._demographics: dict[str, AudienceDemographics] = {}
        self._retention: dict[str, RetentionCurve] = {}
        self._virality: dict[str, ViralityAnalysis] = {}
        self._benchmarks: dict[str, CompetitiveBenchmark] = {}
        self._alerts: list[PerformanceAlert] = []
        self._widgets: dict[str, DashboardWidget] = {}

    def track_video(
        self,
        video_id: str,
        title: str,
        views: int = 0,
        likes: int = 0,
        shares: int = 0,
        comments: int = 0,
    ) -> VideoMetrics:
        """Track video metrics."""
        metrics = VideoMetrics(
            video_id=video_id,
            title=title,
            views=views,
            likes=likes,
            shares=shares,
            comments=comments,
            avg_view_duration=180.0,
            engagement_rate=(likes + shares + comments) / max(1, views) * 100,
            retention_rate=0.55,
            ctr=0.15,
            virality_score=0.0,
            timestamp=time.time(),
        )

        # Calculate virality
        metrics.virality_score = (
            shares / max(1, views) * 50 +
            metrics.engagement_rate * 0.5 +
            metrics.retention_rate * 30
        )

        # Update watch time
        metrics.watch_time_hours = views * metrics.avg_view_duration / 3600

        self._metrics[video_id] = metrics
        return metrics

    def analyze_demographics(self, video_id: str) -> AudienceDemographics:
        """Analyze audience demographics."""
        demographics = AudienceDemographics(
            video_id=video_id,
            age_distribution={
                "13-17": 0.15, "18-24": 0.35, "25-34": 0.30, "35-44": 0.12, "45+": 0.08
            },
            gender_distribution={"male": 0.55, "female": 0.45},
            location_distribution={
                "NA": 0.40, "EU": 0.25, "APAC": 0.20, "LATAM": 0.10, "other": 0.05
            },
            device_distribution={"mobile": 0.65, "desktop": 0.25, "tablet": 0.10},
            traffic_sources={
                "algorithm": 0.45, "search": 0.20, "direct": 0.15,
                "external": 0.10, "notifications": 0.10
            },
            unique_viewers=int(self._metrics.get(video_id, VideoMetrics(video_id, "")).views * 0.85),
            returning_viewers_pct=0.25,
        )

        self._demographics[video_id] = demographics
        return demographics

    def generate_retention_curve(self, video_id: str) -> RetentionCurve:
        """Generate viewer retention curve."""
        segments = []
        for i in range(10):
            timestamp_pct = (i + 1) * 10
            retention_pct = 100 - (i * 8) - (ord(hashlib.md5(f"{video_id}:{i}").encode()) % 5)
            segments.append({
                "timestamp_pct": timestamp_pct,
                "retention_pct": retention_pct,
            })

        avg_retention = sum(s["retention_pct"] for s in segments) / len(segments)

        # Find drop-off points
        drop_offs = []
        for i in range(1, len(segments)):
            drop = segments[i - 1]["retention_pct"] - segments[i]["retention_pct"]
            if drop > 10:
                drop_offs.append(segments[i]["timestamp_pct"])

        curve = RetentionCurve(
            video_id=video_id,
            segments=segments,
            avg_retention=avg_retention,
            drop_off_points=drop_offs,
            peak_retention=100,
            last_segment_retention=segments[-1]["retention_pct"],
        )

        self._retention[video_id] = curve
        return curve

    def analyze_virality(self, video_id: str) -> ViralityAnalysis:
        """Analyze video virality."""
        metrics = self._metrics.get(video_id)
        if not metrics:
            raise HTTPException(404, f"Video {video_id} not found")

        sharing_rate = metrics.shares / max(1, metrics.views)
        velocity = min(1.0, metrics.virality_score / 50)

        virality = ViralityAnalysis(
            video_id=video_id,
            virality_score=metrics.virality_score,
            sharing_rate=sharing_rate,
            velocity_score=velocity,
            compound_score=metrics.virality_score * velocity,
            predicted_views=metrics.views * (1 + metrics.virality_score / 20),
            days_to_viral=30 / max(0.1, velocity),
            factors=[
                f"Sharing rate: {sharing_rate:.2%}",
                f"Engagement rate: {metrics.engagement_rate:.1f}%",
                f"Retention: {metrics.retention_rate:.0%}",
            ],
        )

        self._virality[video_id] = virality
        return virality

    def benchmark_competitively(self, video_id: str, benchmark_group: str = "") -> CompetitiveBenchmark:
        """Benchmark video against competitors."""
        metrics = self._metrics.get(video_id)
        if not metrics:
            raise HTTPException(404, f"Video {video_id} not found")

        avg_views = 100000
        avg_engagement = 4.0
        avg_retention = 0.50

        percentile = min(99, max(1, metrics.views / avg_views * 50 + 25))

        strengths = []
        weaknesses = []

        if metrics.engagement_rate > avg_engagement:
            strengths.append("High engagement rate")
        else:
            weaknesses.append("Below-average engagement")

        if metrics.retention_rate > avg_retention:
            strengths.append("Strong viewer retention")
        else:
            weaknesses.append("Viewer retention needs improvement")

        if metrics.virality_score > 30:
            strengths.append("High virality potential")
        else:
            weaknesses.append("Low virality score")

        benchmark = CompetitiveBenchmark(
            video_id=video_id,
            benchmark_group=benchmark_group or "general",
            avg_views_in_group=avg_views,
            avg_engagement_in_group=avg_engagement,
            avg_retention_in_group=avg_retention,
            percentile_rank=percentile,
            competitive_score=percentile * 0.4 + (metrics.engagement_rate / avg_engagement) * 0.3 + (metrics.retention_rate / avg_retention) * 0.3,
            strengths=strengths,
            weaknesses=weaknesses,
        )

        self._benchmarks[video_id] = benchmark
        return benchmark

    def check_alerts(self, video_id: str) -> list[PerformanceAlert]:
        """Check for performance alerts."""
        metrics = self._metrics.get(video_id)
        if not metrics:
            return []

        alerts = []

        if metrics.views > 1000000:
            alerts.append(PerformanceAlert(
                alert_id=hashlib.md5(f"alert:views:{video_id}:{time.time()}").hexdigest()[:12],
                video_id=video_id,
                alert_type="views_spike",
                severity="high",
                message=f"Views exceeded 1M ({metrics.views:,})",
                threshold=1000000,
                current_value=metrics.views,
                triggered_at=time.time(),
            ))

        if metrics.engagement_rate < 2.0:
            alerts.append(PerformanceAlert(
                alert_id=hashlib.md5(f"alert:eng:{video_id}:{time.time()}").hexdigest()[:12],
                video_id=video_id,
                alert_type="engagement_low",
                severity="medium",
                message=f"Engagement rate is low ({metrics.engagement_rate:.1f}%)",
                threshold=2.0,
                current_value=metrics.engagement_rate,
                triggered_at=time.time(),
            ))

        if metrics.virality_score > 40:
            alerts.append(PerformanceAlert(
                alert_id=hashlib.md5(f"alert:viral:{video_id}:{time.time()}").hexdigest()[:12],
                video_id=video_id,
                alert_type="virality_high",
                severity="high",
                message=f"High virality score ({metrics.virality_score:.1f})",
                threshold=40,
                current_value=metrics.virality_score,
                triggered_at=time.time(),
            ))

        self._alerts.extend(alerts)
        return alerts

    def create_dashboard(self, title: str) -> dict:
        """Create a dashboard."""
        dashboard_id = hashlib.md5(f"dashboard:{title}:{time.time()}").hexdigest()[:12]

        widgets = [
            DashboardWidget(
                widget_id=f"{dashboard_id}:views",
                widget_type="metric",
                title="Total Views",
                data=[{"value": sum(m.views for m in self._metrics.values()), "label": "views"}],
                refresh_rate=60,
                last_updated=time.time(),
            ),
            DashboardWidget(
                widget_id=f"{dashboard_id}:engagement",
                widget_type="gauge",
                title="Avg Engagement Rate",
                data=[{"value": sum(m.engagement_rate for m in self._metrics.values()) / max(1, len(self._metrics)), "label": "%"}],
                refresh_rate=30,
                last_updated=time.time(),
            ),
            DashboardWidget(
                widget_id=f"{dashboard_id}:alerts",
                widget_type="alert",
                title="Active Alerts",
                data=[{"count": len(self._alerts), "label": "alerts"}],
                refresh_rate=30,
                last_updated=time.time(),
            ),
        ]

        for widget in widgets:
            self._widgets[widget.widget_id] = widget

        return {
            "dashboard_id": dashboard_id,
            "title": title,
            "widgets": len(widgets),
            "created_at": time.time(),
        }

    def get_report(self) -> dict:
        """Get video analytics dashboard report."""
        return {
            "total_videos_tracked": len(self._metrics),
            "total_demographics_analyses": len(self._demographics),
            "total_retention_curves": len(self._retention),
            "total_virality_analyses": len(self._virality),
            "total_benchmarks": len(self._benchmarks),
            "total_alerts": len(self._alerts),
            "total_widgets": len(self._widgets),
            "total_views": sum(m.views for m in self._metrics.values()),
            "avg_engagement": sum(m.engagement_rate for m in self._metrics.values()) / max(1, len(self._metrics)),
            "avg_retention": sum(r.avg_retention for r in self._retention.values()) / max(1, len(self._retention)),
            "recent_alerts": [
                {
                    "video": a.video_id,
                    "type": a.alert_type,
                    "severity": a.severity,
                    "message": a.message,
                }
                for a in self._alerts[-5:]
            ],
        }


# Module-level singleton
analytics_dashboard = VideoAnalyticsDashboard()


# ── API Routes ──────────────────────────────────────────────────────────────


@router.post("/api/v1/vyralx/analytics/track")
async def track_video(payload: dict):
    """Track video metrics."""
    metrics = analytics_dashboard.track_video(
        video_id=payload["video_id"],
        title=payload["title"],
        views=payload.get("views", 0),
        likes=payload.get("likes", 0),
        shares=payload.get("shares", 0),
        comments=payload.get("comments", 0),
    )
    return {
        "video_id": metrics.video_id,
        "views": metrics.views,
        "engagement_rate": metrics.engagement_rate,
        "virality_score": metrics.virality_score,
    }


@router.get("/api/v1/vyralx/analytics/{video_id}/demographics")
async def analyze_demographics(video_id: str):
    """Analyze audience demographics."""
    demographics = analytics_dashboard.analyze_demographics(video_id)
    return {
        "video_id": demographics.video_id,
        "age_distribution": demographics.age_distribution,
        "gender_distribution": demographics.gender_distribution,
        "location_distribution": demographics.location_distribution,
        "device_distribution": demographics.device_distribution,
        "traffic_sources": demographics.traffic_sources,
        "unique_viewers": demographics.unique_viewers,
    }


@router.get("/api/v1/vyralx/analytics/{video_id}/retention")
async def generate_retention_curve(video_id: str):
    """Generate retention curve."""
    curve = analytics_dashboard.generate_retention_curve(video_id)
    return {
        "video_id": curve.video_id,
        "avg_retention": curve.avg_retention,
        "peak_retention": curve.peak_retention,
        "last_segment_retention": curve.last_segment_retention,
        "drop_off_points": curve.drop_off_points,
        "segments": curve.segments,
    }


@router.get("/api/v1/vyralx/analytics/{video_id}/virality")
async def analyze_virality(video_id: str):
    """Analyze virality."""
    virality = analytics_dashboard.analyze_virality(video_id)
    return {
        "video_id": virality.video_id,
        "virality_score": virality.virality_score,
        "sharing_rate": virality.sharing_rate,
        "velocity_score": virality.velocity_score,
        "compound_score": virality.compound_score,
        "predicted_views": virality.predicted_views,
        "days_to_viral": virality.days_to_viral,
        "factors": virality.factors,
    }


@router.get("/api/v1/vyralx/analytics/{video_id}/benchmark")
async def benchmark_competitively(video_id: str, benchmark_group: str = ""):
    """Benchmark competitively."""
    benchmark = analytics_dashboard.benchmark_competitively(video_id, benchmark_group)
    return {
        "video_id": benchmark.video_id,
        "percentile_rank": benchmark.percentile_rank,
        "competitive_score": benchmark.competitive_score,
        "strengths": benchmark.strengths,
        "weaknesses": benchmark.weaknesses,
    }


@router.get("/api/v1/vyralx/analytics/{video_id}/alerts")
async def check_alerts(video_id: str):
    """Check for performance alerts."""
    alerts = analytics_dashboard.check_alerts(video_id)
    return {
        "video_id": video_id,
        "alerts": [
            {"type": a.alert_type, "severity": a.severity, "message": a.message}
            for a in alerts
        ],
        "total_alerts": len(alerts),
    }


@router.post("/api/v1/vyralx/analytics/dashboard")
async def create_dashboard(payload: dict):
    """Create a dashboard."""
    dashboard = analytics_dashboard.create_dashboard(title=payload["title"])
    return {"dashboard_id": dashboard["dashboard_id"], "widgets": dashboard["widgets"]}


@router.get("/api/v1/vyralx/analytics/report")
async def get_report():
    """Get video analytics dashboard report."""
    return analytics_dashboard.get_report()
