"""VyralX channel planning and guarded project queueing.

This module never downloads/reuses discovered creators' media and never uploads
directly to YouTube. It discovers *ideas*, queues work through VyralX's existing
VideoProject pipeline, and leaves publication behind the normal rights and
operator-approval gates.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import SessionLocal
from app.models import PublishJob, VideoProject, utcnow
from app.services.discovery import discover_youtube_videos
from app.services.trends import rank_candidates
from app.services.youtube_analytics import fetch_video_metrics

logger = logging.getLogger("vyralx.orchestrator")


def _as_utc(value: datetime) -> datetime:
    """Normalize naive and aware datetimes consistently to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass
class ContentIdea:
    """An original-content idea derived from metadata-only trend research."""

    topic: str
    angle: str
    confidence: float
    source: str
    estimated_views: int = 0
    estimated_retention: float = 0.5
    competitor_url: str = ""
    keywords: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


@dataclass
class ContentPlan:
    """In-memory weekly plan; database project keys provide queue idempotency."""

    week_start: datetime
    ideas: list[ContentIdea] = field(default_factory=list)
    scheduled_dates: dict[str, datetime] = field(default_factory=dict)
    status: str = "DRAFT"

    def add_idea(self, idea: ContentIdea, publish_date: datetime) -> None:
        self.ideas.append(idea)
        self.scheduled_dates[idea.topic] = publish_date

    def due_videos(self, now: datetime | None = None) -> list[tuple[ContentIdea, datetime]]:
        """Return entries whose planned queue time has arrived."""
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        return sorted(
            (
                (idea, _as_utc(planned))
                for idea in self.ideas
                if (planned := self.scheduled_dates.get(idea.topic)) is not None
                and _as_utc(planned) <= current
            ),
            key=lambda pair: pair[1],
        )

    def upcoming_videos(self, now: datetime | None = None) -> list[tuple[ContentIdea, datetime]]:
        """Return entries scheduled after now."""
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        return sorted(
            (
                (idea, _as_utc(planned))
                for idea in self.ideas
                if (planned := self.scheduled_dates.get(idea.topic)) is not None
                and _as_utc(planned) > current
            ),
            key=lambda pair: pair[1],
        )


@dataclass
class ChannelMetrics:
    """Aggregate public performance counters for uploads that belong to VyralX."""

    total_views: int = 0
    total_subscribers: int = 0
    avg_retention: float = 0.0
    avg_ctr: float = 0.0
    top_video_title: str = ""
    top_video_views: int = 0
    engagement_rate: float = 0.0
    upload_frequency: str = ""
    best_publish_time: str = ""
    best_day_of_week: str = ""


class AutonomousChannelOrchestrator:
    """Discover trends and queue guarded VyralX projects.

    Enable queueing only after the operator explicitly confirms the intended
    Pexels license review in environment configuration. Uploads are never made
    by this class; VyralX's normal PublishJob workflow owns publication.
    """

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.content_history: list[ContentIdea] = []
        self.performance_history: list[ChannelMetrics] = []
        self.idea_pool: list[ContentIdea] = []
        self._running = False
        self._stop_event = asyncio.Event()

    def _discovery_query(self) -> str:
        niche = " ".join(str(getattr(self.settings, "channel_niche", "") or "").split())
        pillars = " ".join(
            value.strip()
            for value in str(getattr(self.settings, "channel_content_pillars", "") or "").split(",")
            if value.strip()
        )
        query = " ".join(part for part in (niche, pillars) if part)
        return query[:200] or "educational technology science explainers"

    async def discover_trends(self, limit: int = 20) -> list[ContentIdea]:
        """Fetch real YouTube metadata, rank it locally, and return ideas only."""
        limit = max(1, min(int(limit), 25))
        query = self._discovery_query()
        try:
            candidates = await asyncio.to_thread(
                discover_youtube_videos,
                query=query,
                max_results=limit,
                order="date",
            )
            ranked = rank_candidates(candidates)
        except Exception as exc:
            logger.warning("Trend discovery unavailable (%s)", type(exc).__name__)
            return []

        ideas: list[ContentIdea] = []
        for item in ranked:
            title = " ".join(str(item.get("title") or "").split())[:500]
            if not title:
                continue
            # A trend title is a research signal, not a script to copy or a media license.
            ideas.append(
                ContentIdea(
                    topic=title,
                    angle=f"Create an original explainer about: {title}",
                    confidence=max(0.0, min(1.0, float(item.get("trend_score", 0.0)) / 100.0)),
                    source="metadata_trend_research",
                    estimated_views=max(0, int(item.get("view_count") or 0)),
                    competitor_url=str(item.get("url") or "")[:2048],
                    keywords=self._extract_keywords(title),
                )
            )
        ideas = self._rank_ideas(ideas)[:limit]
        self.idea_pool.extend(ideas)
        # Bound memory growth on a long-lived worker.
        self.idea_pool = self.idea_pool[-500:]
        logger.info("Discovered %d metadata-only content ideas", len(ideas))
        return ideas

    @staticmethod
    def _extract_angle(title: str) -> str:
        title = re.sub(
            r"^(I |We |You |The |A |An |Why |How |What |When |Where |Who |Is |Are |Do |Does |Can |Will |Would |Should) ",
            "",
            title.strip(),
        )
        title = re.sub(r"[\.\?!:]+$", "", title)
        return title[:100] or "Original educational angle"

    @staticmethod
    def _estimate_confidence(video: dict[str, Any]) -> float:
        score = video.get("trend_score")
        if isinstance(score, (int, float)):
            return max(0.0, min(1.0, float(score) / 100.0))
        views = max(0, int(video.get("view_count", video.get("views", 0)) or 0))
        return min(0.95, 0.3 + (0.1 * (len(str(views)) - 1)))

    @staticmethod
    def _extract_keywords(title: str) -> list[str]:
        stop_words = {"the", "and", "for", "with", "from", "that", "this", "your", "you"}
        words = re.findall(r"[a-zA-Z0-9]+", title.lower())
        return list(dict.fromkeys(word for word in words if len(word) > 3 and word not in stop_words))[:10]

    @staticmethod
    def _rank_ideas(ideas: list[ContentIdea]) -> list[ContentIdea]:
        return sorted(ideas, key=lambda idea: (idea.confidence, idea.estimated_views), reverse=True)

    async def generate_weekly_plan(self) -> ContentPlan:
        """Plan five weekly ideas and mark the first one immediately due."""
        ideas = await self.discover_trends(limit=25)
        now = datetime.now(timezone.utc)
        plan = ContentPlan(week_start=now)
        offsets = (0, 1, 3, 5, 6)
        for index, idea in enumerate(ideas[: len(offsets)]):
            plan.add_idea(idea, now + timedelta(days=offsets[index]))
        plan.status = "PLANNED"
        logger.info("Weekly plan generated: %d ideas", len(plan.ideas))
        return plan

    async def produce_video(self, idea: ContentIdea) -> dict[str, Any]:
        """Queue a project through VyralX's tested production pipeline.

        No placeholder file is returned and this method does not bypass the
        existing PublishJob approval workflow.
        """
        if not bool(getattr(self.settings, "autonomous_channel_enabled", False)):
            return {
                "status": "AWAITING_OPERATOR_CONFIGURATION",
                "topic": idea.topic,
                "required_settings": ["AUTONOMOUS_CHANNEL_ENABLED=true"],
                "message": "Autonomous project queueing is disabled; no work was queued.",
            }
        if not bool(getattr(self.settings, "autonomous_pexels_license_confirmed", False)):
            return {
                "status": "AWAITING_LICENSE_CONFIRMATION",
                "topic": idea.topic,
                "required_settings": ["AUTONOMOUS_PEXELS_LICENSE_CONFIRMED=true"],
                "message": "Explicit operator confirmation of the Pexels license review is required.",
            }

        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        digest = hashlib.sha256(f"{now.date().isoformat()}:{idea.topic.casefold()}".encode()).hexdigest()[:24]
        project_key = f"auto_{digest}"
        session = SessionLocal()
        try:
            existing = session.scalar(select(VideoProject).where(VideoProject.project_key == project_key))
            if existing is not None:
                return {
                    "status": existing.status.upper(),
                    "project_id": existing.id,
                    "project_key": existing.project_key,
                    "idempotent_replay": True,
                    "publication": "requires separate operator approval",
                }
            created_today = session.scalar(
                select(func.count(VideoProject.id)).where(VideoProject.created_at >= day_start)
            ) or 0
            daily_limit = max(1, min(5, int(getattr(self.settings, "autonomous_daily_project_limit", 1))))
            if created_today >= daily_limit:
                return {
                    "status": "DAILY_LIMIT_REACHED",
                    "limit": daily_limit,
                    "created_today": created_today,
                    "topic": idea.topic,
                }

            project = VideoProject(
                project_key=project_key,
                topic=idea.topic[:500],
                auto_discover_trend=False,
                trend_query="",
                trend_max_results=10,
                video_format="shorts",
                target_seconds=45,
                audience="general audience",
                tone="clear, energetic and factual",
                scene_count=4,
                confirm_pexels_license=True,
                # Do not opt into reuse permission by inference.
                confirm_pexels_repeat_use=False,
                use_voiceover=True,
                status="queued",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(project)
            session.commit()
            session.refresh(project)
            self.content_history.append(idea)
            return {
                "status": "QUEUED_FOR_PRODUCTION",
                "project_id": project.id,
                "project_key": project.project_key,
                "idempotent_replay": False,
                "publication": "requires existing VyralX rights checks and operator approval",
            }
        except IntegrityError:
            session.rollback()
            existing = session.scalar(select(VideoProject).where(VideoProject.project_key == project_key))
            if existing is not None:
                return {
                    "status": existing.status.upper(),
                    "project_id": existing.id,
                    "project_key": existing.project_key,
                    "idempotent_replay": True,
                    "publication": "requires separate operator approval",
                }
            raise
        except Exception:
            session.rollback()
            logger.exception("Could not queue VyralX project")
            return {"status": "QUEUE_ERROR", "topic": idea.topic}
        finally:
            session.close()

    async def _render_video(self, content_pack: dict[str, Any]):
        """Direct rendering is intentionally delegated to project_pipeline."""
        raise RuntimeError(
            "Direct placeholder rendering is disabled; queue a VideoProject so VyralX can verify assets, rights, audio, and output."
        )

    async def analyze_performance(self) -> ChannelMetrics:
        """Analyze public metrics only for videos published by this VyralX database."""
        metrics = ChannelMetrics()
        session = SessionLocal()
        try:
            rows = session.scalars(
                select(PublishJob)
                .where(PublishJob.status == "completed", PublishJob.youtube_video_id != "")
                .order_by(PublishJob.completed_at.desc())
                .limit(50)
            ).all()
            video_ids = list(dict.fromkeys(
                str(row.youtube_video_id).strip()
                for row in rows
                if row.youtube_video_id and str(row.youtube_video_id).strip()
            ))
            titles = {str(row.youtube_video_id): row.title for row in rows if row.youtube_video_id}
        except Exception as exc:
            session.rollback()
            logger.warning("Could not read VyralX upload history (%s)", type(exc).__name__)
            return metrics
        finally:
            session.close()

        if not video_ids:
            return metrics
        try:
            data = await asyncio.to_thread(fetch_video_metrics, video_ids)
        except Exception as exc:
            logger.warning("Performance analysis unavailable (%s)", type(exc).__name__)
            return metrics
        if not data:
            return metrics

        metrics.total_views = sum(max(0, int(item.get("view_count") or 0)) for item in data)
        metrics.engagement_rate = (
            sum(float(item.get("engagement_rate") or 0.0) for item in data) / len(data)
        )
        top = max(data, key=lambda item: int(item.get("view_count") or 0))
        metrics.top_video_views = max(0, int(top.get("view_count") or 0))
        metrics.top_video_title = str(top.get("title") or titles.get(str(top.get("youtube_video_id")), ""))
        self.performance_history.append(metrics)
        self.performance_history = self.performance_history[-100:]
        return metrics

    async def self_improve(self) -> dict[str, Any]:
        """Return bounded observations; strategy is not allowed to change rights gates."""
        metrics = await self.analyze_performance()
        insights: dict[str, Any] = {
            "avg_retention": metrics.avg_retention,
            "avg_ctr": metrics.avg_ctr,
            "engagement_rate": metrics.engagement_rate,
            "best_publish_time": metrics.best_publish_time,
            "top_video": metrics.top_video_title,
        }
        actions = []
        if metrics.avg_retention and metrics.avg_retention < 0.4:
            actions.append("Review opening hooks and pacing")
        if metrics.avg_ctr and metrics.avg_ctr < 0.03:
            actions.append("Review thumbnail readability and title clarity")
        if metrics.top_video_title:
            actions.append("Use the top video as a research signal for an original follow-up")
        insights["actions"] = actions
        logger.info("Self-improvement observations: %s", insights)
        return insights

    async def run_autonomous_loop(self) -> None:
        """Run daily discovery and guarded project queueing until stopped."""
        if self._running:
            logger.warning("Autonomous channel loop is already running")
            return
        self._running = True
        self._stop_event.clear()
        logger.info("Starting guarded VyralX channel orchestrator")
        try:
            while not self._stop_event.is_set():
                delay = 86400
                try:
                    plan = await self.generate_weekly_plan()
                    for idea, _scheduled_at in plan.due_videos():
                        if self._stop_event.is_set():
                            break
                        result = await self.produce_video(idea)
                        logger.info("Project queue result: %s", result)
                    await self.self_improve()
                except Exception:
                    logger.exception("Autonomous channel cycle failed")
                    delay = 300
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
        finally:
            self._running = False
            logger.info("Stopped VyralX channel orchestrator")

    async def stop(self) -> None:
        """Request a cooperative stop; the loop checks the event between cycles."""
        self._stop_event.set()


autonomous_orchestrator = AutonomousChannelOrchestrator()
