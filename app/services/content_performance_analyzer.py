"""
VyralX/app/services/content_performance_analyzer.py — VyralX Content Performance Analyzer.

Content performance metrics, engagement analysis, trend detection,
and content strategy recommendations.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class ContentMetric:
    """Performance metrics for a content piece."""
    content_id: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    watch_time_sec: float = 0.0
    engagement_rate: float = 0.0
    retention_rate: float = 0.0
    discovery_source: str = "unknown"


@dataclass
class TrendAnalysis:
    """Trend analysis for content."""
    topic: str
    trend_direction: str = "stable"  # increasing, decreasing, stable
    growth_rate: float = 0.0
    peak_time: float = 0.0
    data_points: list[dict] = field(default_factory=list)


@dataclass
class PerformanceReport:
    """A content performance report."""
    report_id: str
    channel_id: str
    total_content: int = 0
    avg_views: float = 0.0
    avg_engagement: float = 0.0
    top_content: list[str] = field(default_factory=list)
    trends: list[TrendAnalysis] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)


class ContentPerformanceAnalyzer:
    """Engine for content performance analysis."""

    def __init__(self) -> None:
        self._metrics: dict[str, ContentMetric] = {}
        self._trends: dict[str, TrendAnalysis] = {}
        self._reports: list[PerformanceReport] = []

    def record_metric(self, content_id: str, views: int, likes: int,
                      comments: int, shares: int, watch_time_sec: float,
                      discovery_source: str = "unknown") -> ContentMetric:
        """Record content performance metrics."""
        metric = ContentMetric(
            content_id=content_id, views=views, likes=likes,
            comments=comments, shares=shares, watch_time_sec=watch_time_sec,
            discovery_source=discovery_source,
        )
        metric.engagement_rate = (likes + comments + shares) / max(1, views)
        metric.retention_rate = min(1.0, watch_time_sec / 60.0)
        self._metrics[content_id] = metric
        return metric

    def analyze_trends(self, topic: str, data_points: list[dict]) -> TrendAnalysis:
        """Analyze trends for a topic."""
        trend_id = f"trend_{uuid.uuid4().hex[:12]}"
        trend = TrendAnalysis(topic=topic)
        if len(data_points) >= 2:
            recent = data_points[-5:]
            older = data_points[:-5]
            recent_views = sum(d.get("views", 0) for d in recent)
            older_views = sum(d.get("views", 0) for d in older) if older else recent_views
            if older_views > 0:
                trend.growth_rate = (recent_views - older_views) / older_views
                trend.trend_direction = "increasing" if trend.growth_rate > 0.1 else "decreasing" if trend.growth_rate < -0.1 else "stable"
            peak = max(data_points, key=lambda d: d.get("views", 0))
            trend.peak_time = peak.get("timestamp", 0)
        trend.data_points = data_points
        self._trends[trend_id] = trend
        return trend

    def generate_report(self, channel_id: str) -> PerformanceReport:
        """Generate a performance report for a channel."""
        report_id = f"report_{uuid.uuid4().hex[:12]}"
        report = PerformanceReport(report_id=report_id, channel_id=channel_id)
        metrics = list(self._metrics.values())
        report.total_content = len(metrics)

        if metrics:
            report.avg_views = sum(m.views for m in metrics) / len(metrics)
            report.avg_engagement = sum(m.engagement_rate for m in metrics) / len(metrics)
            top = sorted(metrics, key=lambda m: m.views, reverse=True)[:5]
            report.top_content = [m.content_id for m in top]

        for trend in self._trends.values():
            report.trends.append(trend)

        self._reports.append(report)
        return report

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_metrics": len(self._metrics),
            "total_trends": len(self._trends),
            "total_reports": len(self._reports),
            "engine_status": "operational",
        }


engine = ContentPerformanceAnalyzer()


@router.post("/vyralx/performance/metrics")
async def record_metric(content_id: str, views: int, likes: int, comments: int,
                        shares: int, watch_time_sec: float, discovery_source: str = "unknown"):
    """Record content performance metrics."""
    metric = engine.record_metric(content_id, views, likes, comments, shares, watch_time_sec, discovery_source)
    return {"content_id": content_id, "engagement_rate": metric.engagement_rate}


@router.post("/vyralx/performance/trends")
async def analyze_trends(topic: str, data_points: list[dict]):
    """Analyze content trends."""
    trend = engine.analyze_trends(topic, data_points)
    return {"topic": trend.topic, "trend_direction": trend.trend_direction, "growth_rate": trend.growth_rate}


@router.post("/vyralx/performance/report")
async def generate_report(channel_id: str):
    """Generate a performance report."""
    report = engine.generate_report(channel_id)
    return {
        "report_id": report.report_id,
        "total_content": report.total_content,
        "avg_views": report.avg_views,
        "avg_engagement": report.avg_engagement,
    }


@router.get("/vyralx/performance/report")
async def performance_report():
    """Get performance analyzer report."""
    return engine.get_report()
