"""
VyralX/app/services/channel_growth_strategy.py — VyralX Channel Growth Strategy Engine.

Extends VyralX's capabilities with:
1. Growth Loop Design: design viral growth loops
2. Retention Funnel Optimization: optimize viewer retention
3. Content Cadence Strategy: determine optimal posting frequency
4. Channel Expansion Plans: plan channel growth phases
5. Competitive Analysis: analyze competitor channels
6. Audience Expansion Strategy: plan audience growth
7. Monetization Strategy: plan revenue growth
8. Growth KPI Tracking: track growth metrics
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class GrowthLoop:
    """A viral growth loop design."""
    loop_id: str
    name: str
    trigger: str
    action: str
    reward: str
    viral_coefficient: float = 0.0
    estimated_growth: float = 0.0
    description: str = ""


@dataclass
class RetentionFunnel:
    """Viewer retention funnel."""
    stage: str  # impression, click, view, subscribe, engage
    conversion_rate: float = 0.0
    target_rate: float = 0.0
    dropoff: float = 0.0
    improvement: str = ""


@dataclass
class ContentCadence:
    """Content posting cadence strategy."""
    days_per_week: int = 5
    optimal_post_times: list[str] = field(default_factory=list)
    content_types: list[str] = field(default_factory=list)
    rest_days: list[str] = field(default_factory=list)
    estimated_burnout_risk: float = 0.0
    growth_impact: str = ""


@dataclass
class ChannelPhase:
    """A channel growth phase."""
    phase: str  # launch, growth, expansion, maturity
    duration_weeks: int = 4
    goals: list[str] = field(default_factory=list)
    content_focus: list[str] = field(default_factory=list)
    milestones: list[str] = field(default_factory=list)
    kpis: list[str] = field(default_factory=list)


@dataclass
class CompetitorAnalysis:
    """Competitor channel analysis."""
    channel_name: str
    subscribers: int = 0
    avg_views: int = 0
    posting_frequency: float = 0.0
    top_content: list[str] = field(default_factory=list)
    growth_rate: float = 0.0
    engagement_rate: float = 0.0
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)


@dataclass
class MonetizationPlan:
    """Monetization strategy plan."""
    revenue_streams: list[str] = field(default_factory=list)
    projected_monthly_revenue: float = 0.0
    rpm: float = 0.0  # revenue per mille
    ad_readiness: float = 0.0
    sponsorship_readiness: float = 0.0
    merch_readiness: float = 0.0
    timeline: list[str] = field(default_factory=list)


@dataclass
class GrowthKPI:
    """Growth KPI tracking."""
    metric: str  # subscribers, views, watch_time, engagement, revenue
    current: float = 0.0
    target: float = 0.0
    growth_rate: float = 0.0
    trend: str = "stable"  # growing, stable, declining
    projected_month: float = 0.0
    status: str = "on_track"  # on_track, at_risk, behind


@dataclass
class GrowthStrategy:
    """Overall growth strategy."""
    strategy_id: str
    vision: str
    phases: list[ChannelPhase] = field(default_factory=list)
    loops: list[GrowthLoop] = field(default_factory=list)
    kpis: list[GrowthKPI] = field(default_factory=list)
    monetization: MonetizationPlan | None = None
    estimated_timeline: str = ""
    risk_factors: list[str] = field(default_factory=list)


class ChannelGrowthStrategist:
    """Channel growth strategy engine."""

    def __init__(self):
        self._strategies: dict[str, GrowthStrategy] = {}
        self._competitors: dict[str, CompetitorAnalysis] = {}
        self._kpis: dict[str, GrowthKPI] = {}
        self._loops: list[GrowthLoop] = []

    # ── Growth Loop Design ────────────────────────────────────────────────

    def design_growth_loop(
        self,
        name: str,
        trigger: str,
        action: str,
        reward: str,
        viral_coefficient: float = 0.0,
    ) -> GrowthLoop:
        """Design a viral growth loop."""
        # Calculate projected growth
        # K = viral coefficient, if K > 1, exponential growth
        projected_growth = viral_coefficient * 100

        loop = GrowthLoop(
            loop_id=hashlib.md5(f"loop:{name}:{time.time()}".encode()).hexdigest()[:12],
            name=name,
            trigger=trigger,
            action=action,
            reward=reward,
            viral_coefficient=viral_coefficient,
            estimated_growth=projected_growth,
            description=f"{trigger} → {action} → {reward}",
        )

        self._loops.append(loop)
        return loop

    def get_growth_loops(self) -> list[GrowthLoop]:
        return sorted(self._loops, key=lambda l: -l.viral_coefficient)

    def optimize_loops(self) -> list[GrowthLoop]:
        """Optimize growth loops."""
        for loop in self._loops:
            if loop.viral_coefficient < 0.3:
                # Suggest improvements
                if "share" not in loop.action.lower():
                    loop.action = f"{loop.action} + share prompt"
                if "reward" not in loop.reward.lower():
                    loop.reward = f"{loop.reward} + social proof"
                loop.viral_coefficient = min(1.0, loop.viral_coefficient * 1.5)
                loop.estimated_growth = loop.viral_coefficient * 100

        return self._loops

    # ── Retention Funnel Optimization ────────────────────────────────────

    def build_retention_funnel(
        self,
        metrics: dict[str, float],
    ) -> list[RetentionFunnel]:
        """Build and optimize retention funnel."""
        stages = [
            ("impression", "click_through", 0.05, "thumbnail, title"),
            ("click", "view_start", 0.90, "intro hook"),
            ("view_start", "watch_30s", 0.70, "content quality"),
            ("watch_30s", "watch_50%", 0.50, "pacing, value"),
            ("watch_50%", "subscribe", 0.10, "call to action"),
            ("subscribe", "engage", 0.30, "community building"),
        ]

        funnel = []
        for i, (stage, next_stage, rate, focus) in enumerate(stages):
            actual = metrics.get(stage, rate)
            dropoff = 1.0 - (actual / rate if rate > 0 else 1.0)

            improvement = ""
            if dropoff > 0.3:
                improvement = f"Focus on {focus} to improve {stage}→{next_stage} conversion"

            funnel.append(RetentionFunnel(
                stage=stage,
                conversion_rate=actual,
                target_rate=rate,
                dropoff=dropoff,
                improvement=improvement,
            ))

        return funnel

    # ── Content Cadence Strategy ─────────────────────────────────────────

    def determine_content_cadence(
        self,
        audience_size: int,
        production_capacity: int,
        growth_stage: str = "growth",
    ) -> ContentCadence:
        """Determine optimal content posting cadence."""
        if growth_stage == "launch":
            days = 5
            burnout_risk = 0.3
            impact = "High frequency builds initial momentum"
        elif growth_stage == "growth":
            days = 4
            burnout_risk = 0.2
            impact = "Consistent posting drives algorithmic growth"
        elif growth_stage == "expansion":
            days = 3
            burnout_risk = 0.1
            impact = "Quality-focused posting sustains growth"
        else:
            days = 2
            burnout_risk = 0.05
            impact = "Premium content maintains subscriber loyalty"

        # Adjust for production capacity
        days = min(days, production_capacity)

        optimal_times = {
            "monday": ["09:00", "18:00"],
            "tuesday": ["12:00", "20:00"],
            "wednesday": ["09:00", "18:00"],
            "thursday": ["12:00", "20:00"],
            "friday": ["10:00", "19:00"],
        }

        all_times = []
        for times in optimal_times.values():
            all_times.extend(times)

        rest_days = ["saturday", "sunday"] if days <= 4 else ["sunday"]

        return ContentCadence(
            days_per_week=days,
            optimal_post_times=all_times,
            content_types=["shorts", "long_form", "community"],
            rest_days=rest_days,
            estimated_burnout_risk=burnout_risk,
            growth_impact=impact,
        )

    # ── Channel Expansion Plans ──────────────────────────────────────────

    def create_expansion_plan(
        self,
        current_subscribers: int,
        current_views: int,
        target_subscribers: int,
    ) -> list[ChannelPhase]:
        """Create channel expansion plan."""
        phases = []

        if current_subscribers < 1000:
            phases.append(ChannelPhase(
                phase="launch",
                duration_weeks=4,
                goals=["Find content-market fit", "Establish posting rhythm", "Build initial audience"],
                content_focus=["Shorts for discovery", "Niche content for retention"],
                milestones=["100 subscribers", "10K views", "10 engaged comments"],
                kpis=["subscriber_growth_rate", "avg_view_duration", "click_through_rate"],
            ))

        if current_subscribers < 10000:
            phases.append(ChannelPhase(
                phase="growth",
                duration_weeks=8,
                goals=["Accelerate growth", "Optimize content", "Build community"],
                content_focus=["High-engagement topics", "Community interaction", "Collaborations"],
                milestones=["1K subscribers", "100K total views", "10% engagement rate"],
                kpis=["subscriber_growth_rate", "engagement_rate", "watch_time"],
            ))

        if current_subscribers < 100000:
            phases.append(ChannelPhase(
                phase="expansion",
                duration_weeks=12,
                goals=["Scale content production", "Expand topics", "Monetize channel"],
                content_focus=["Diverse content", "Series & playlists", "Cross-platform"],
                milestones=["10K subscribers", "1M total views", "Ad revenue enabled"],
                kpis=["subscriber_growth_rate", "revenue_per_view", "audience_retention"],
            ))

        phases.append(ChannelPhase(
            phase="maturity",
            duration_weeks=12,
            goals=["Sustain growth", "Optimize revenue", "Build brand"],
            content_focus=["Premium content", "Sponsorships", "Merchandise"],
            milestones=["100K subscribers", "Stable revenue", "Brand partnerships"],
            kpis=["revenue_growth", "subscriber_retention", "brand_deals"],
        ))

        return phases

    # ── Competitive Analysis ─────────────────────────────────────────────

    def analyze_competitor(
        self,
        name: str,
        subscribers: int,
        avg_views: int,
        posting_frequency: float,
        top_content: list[str],
        growth_rate: float,
        engagement_rate: float,
    ) -> CompetitorAnalysis:
        """Analyze a competitor channel."""
        analysis = CompetitorAnalysis(
            channel_name=name,
            subscribers=subscribers,
            avg_views=avg_views,
            posting_frequency=posting_frequency,
            top_content=top_content,
            growth_rate=growth_rate,
            engagement_rate=engagement_rate,
        )

        # Identify strengths and weaknesses
        if engagement_rate > 0.05:
            analysis.strengths.append("High engagement rate")
        if avg_views > subscribers * 0.3:
            analysis.strengths.append("Strong content discovery")
        if posting_frequency > 3:
            analysis.strengths.append("Consistent posting")
        else:
            analysis.weaknesses.append("Infrequent posting")
        if growth_rate < 0.05:
            analysis.weaknesses.append("Slow growth")

        # Opportunities
        if engagement_rate < 0.03:
            analysis.opportunities.append("Improve community engagement")
        if avg_views < subscribers * 0.2:
            analysis.opportunities.append("Improve content discovery")

        self._competitors[name] = analysis
        return analysis

    def get_competitor_insights(self) -> dict:
        """Get insights from all competitors."""
        if not self._competitors:
            return {"insights": "No competitors analyzed"}

        avg_engagement = sum(
            c.engagement_rate for c in self._competitors.values()
        ) / len(self._competitors)

        avg_growth = sum(
            c.growth_rate for c in self._competitors.values()
        ) / len(self._competitors)

        return {
            "competitors_analyzed": len(self._competitors),
            "avg_engagement_rate": avg_engagement,
            "avg_growth_rate": avg_growth,
            "opportunities": list(set(
                o for c in self._competitors.values() for o in c.opportunities
            )),
        }

    # ── Monetization Strategy ────────────────────────────────────────────

    def create_monetization_plan(
        self,
        subscribers: int,
        avg_views: int,
        engagement_rate: float,
    ) -> MonetizationPlan:
        """Create monetization plan."""
        streams = []
        revenue = 0.0
        timeline = []

        # Ad revenue
        if subscribers >= 1000 and avg_views >= 4000:
            streams.append("ads")
            revenue += avg_views * 0.005  # $5 per 1000 views
            timeline.append("Enable ads once criteria met")

        # Sponsorships
        if subscribers >= 5000:
            streams.append("sponsorships")
            revenue += subscribers * 0.01  # $0.01 per subscriber/month
            timeline.append("Pursue brand partnerships")

        # Merchandise
        if subscribers >= 10000:
            streams.append("merchandise")
            revenue += subscribers * 0.02
            timeline.append("Launch merchandise line")

        # Memberships
        if subscribers >= 25000:
            streams.append("memberships")
            revenue += subscribers * 0.015
            timeline.append("Add membership tier")

        # Affiliate
        streams.append("affiliate")
        revenue += avg_views * 0.001

        plan = MonetizationPlan(
            revenue_streams=streams,
            projected_monthly_revenue=revenue,
            rpm=revenue / max(1, avg_views) * 1000,
            ad_readiness=1.0 if subscribers >= 1000 else subscribers / 1000,
            sponsorship_readiness=1.0 if subscribers >= 5000 else subscribers / 5000,
            merch_readiness=1.0 if subscribers >= 10000 else subscribers / 10000,
            timeline=timeline,
        )

        return plan

    # ── Growth KPI Tracking ──────────────────────────────────────────────

    def track_kpi(
        self,
        metric: str,
        current: float,
        target: float,
        growth_rate: float = 0.0,
    ) -> GrowthKPI:
        """Track a growth KPI."""
        trend = "growing" if growth_rate > 0.05 else "stable" if growth_rate > 0 else "declining"
        status = (
            "on_track" if growth_rate > 0.03 else
            "at_risk" if growth_rate > 0 else
            "behind"
        )

        projected = current * (1 + growth_rate)

        kpi = GrowthKPI(
            metric=metric,
            current=current,
            target=target,
            growth_rate=growth_rate,
            trend=trend,
            projected_month=projected,
            status=status,
        )

        self._kpis[metric] = kpi
        return kpi

    def get_growth_dashboard(self) -> dict:
        """Get comprehensive growth dashboard."""
        if not self._kpis:
            return {"status": "No KPIs tracked yet"}

        return {
            "kpis": [k.__dict__ for k in self._kpis.values()],
            "growth_loops": [l.__dict__ for l in self._loops],
            "competitor_insights": self.get_competitor_insights(),
            "competitors_analyzed": len(self._competitors),
        }


# ── API Routes ──────────────────────────────────────────────────────────────

growth_strategist = ChannelGrowthStrategist()


@router.post("/api/v1/growth/loops")
async def design_growth_loop(payload: dict):
    """Design a growth loop."""
    loop = growth_strategist.design_growth_loop(
        name=payload["name"],
        trigger=payload["trigger"],
        action=payload["action"],
        reward=payload["reward"],
        viral_coefficient=payload.get("viral_coefficient", 0.0),
    )
    return loop.__dict__


@router.get("/api/v1/growth/loops")
async def get_growth_loops():
    """Get all growth loops."""
    loops = growth_strategist.get_growth_loops()
    return [l.__dict__ for l in loops]


@router.post("/api/v1/growth/loops/optimize")
async def optimize_loops():
    """Optimize growth loops."""
    loops = growth_strategist.optimize_loops()
    return [l.__dict__ for l in loops]


@router.post("/api/v1/growth/retention_funnel")
async def build_retention_funnel(payload: dict):
    """Build retention funnel."""
    funnel = growth_strategist.build_retention_funnel(payload["metrics"])
    return [f.__dict__ for f in funnel]


@router.post("/api/v1/growth/cadence")
async def determine_cadence(payload: dict):
    """Determine content cadence."""
    cadence = growth_strategist.determine_content_cadence(
        audience_size=payload["audience_size"],
        production_capacity=payload["production_capacity"],
        growth_stage=payload.get("growth_stage", "growth"),
    )
    return cadence.__dict__


@router.post("/api/v1/growth/expansion_plan")
async def create_expansion_plan(payload: dict):
    """Create expansion plan."""
    phases = growth_strategist.create_expansion_plan(
        current_subscribers=payload["current_subscribers"],
        current_views=payload["current_views"],
        target_subscribers=payload["target_subscribers"],
    )
    return [p.__dict__ for p in phases]


@router.post("/api/v1/growth/competitor")
async def analyze_competitor(payload: dict):
    """Analyze competitor."""
    analysis = growth_strategist.analyze_competitor(
        name=payload["name"],
        subscribers=payload["subscribers"],
        avg_views=payload["avg_views"],
        posting_frequency=payload["posting_frequency"],
        top_content=payload.get("top_content", []),
        growth_rate=payload["growth_rate"],
        engagement_rate=payload["engagement_rate"],
    )
    return analysis.__dict__


@router.get("/api/v1/growth/competitor_insights")
async def get_competitor_insights():
    """Get competitor insights."""
    return growth_strategist.get_competitor_insights()


@router.post("/api/v1/growth/monetization")
async def create_monetization_plan(payload: dict):
    """Create monetization plan."""
    plan = growth_strategist.create_monetization_plan(
        subscribers=payload["subscribers"],
        avg_views=payload["avg_views"],
        engagement_rate=payload["engagement_rate"],
    )
    return plan.__dict__


@router.post("/api/v1/growth/kpis")
async def track_kpi(payload: dict):
    """Track a KPI."""
    kpi = growth_strategist.track_kpi(
        metric=payload["metric"],
        current=payload["current"],
        target=payload["target"],
        growth_rate=payload.get("growth_rate", 0.0),
    )
    return kpi.__dict__


@router.get("/api/v1/growth/dashboard")
async def get_growth_dashboard():
    """Get growth dashboard."""
    return growth_strategist.get_growth_dashboard()
