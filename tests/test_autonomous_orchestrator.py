from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.services.autonomous_orchestrator as orchestrator_module
from app.models import VideoProject
from app.services.autonomous_orchestrator import (
    AutonomousChannelOrchestrator,
    ContentIdea,
    ContentPlan,
)


def _idea(topic: str = "Why batteries degrade") -> ContentIdea:
    return ContentIdea(
        topic=topic,
        angle=f"An original explainer about {topic}",
        confidence=0.8,
        source="metadata_trend_research",
        estimated_views=12_000,
        competitor_url="https://www.youtube.com/watch?v=abcdefghijk",
        keywords=["batteries", "science"],
    )


def test_content_plan_separates_due_and_future_videos_and_normalizes_naive_utc():
    now = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
    due = _idea("Due topic")
    future = _idea("Future topic")
    plan = ContentPlan(week_start=now)
    plan.add_idea(due, now - timedelta(minutes=1))
    plan.add_idea(future, datetime(2026, 10, 25, 10, 0))  # legacy naive UTC schedule

    assert [idea.topic for idea, _ in plan.due_videos(now)] == ["Due topic"]
    upcoming = plan.upcoming_videos(now)
    assert [idea.topic for idea, _ in upcoming] == ["Future topic"]
    assert upcoming[0][1].tzinfo is timezone.utc


@pytest.mark.asyncio
async def test_discovery_uses_real_sync_provider_signature_and_keeps_results_metadata_only(monkeypatch):
    settings = SimpleNamespace(
        channel_niche="science",
        channel_content_pillars="space, clean energy",
    )
    seen = {}

    def fake_discovery(query: str, max_results: int = 10, order: str = "viewCount"):
        seen.update(query=query, max_results=max_results, order=order)
        return [
            {
                "video_id": "abcdefghijk",
                "url": "https://www.youtube.com/watch?v=abcdefghijk",
                "title": "Why new batteries degrade over time",
                "channel_title": "Example Channel",
                "view_count": 12000,
                "like_count": 300,
                "comment_count": 35,
                "published_at": "2026-10-23T10:00:00Z",
                "discovery_only": True,
                "rights_verified": False,
            }
        ]

    monkeypatch.setattr(orchestrator_module, "discover_youtube_videos", fake_discovery)
    monkeypatch.setattr(
        orchestrator_module,
        "rank_candidates",
        lambda candidates: [{**candidates[0], "trend_score": 78.5}],
    )

    ideas = await AutonomousChannelOrchestrator(settings).discover_trends(limit=4)

    assert seen == {
        "query": "science space clean energy",
        "max_results": 4,
        "order": "date",
    }
    assert len(ideas) == 1
    assert ideas[0].topic == "Why new batteries degrade over time"
    assert ideas[0].confidence == pytest.approx(0.785)
    assert ideas[0].estimated_views == 12000
    assert ideas[0].source == "metadata_trend_research"
    assert ideas[0].competitor_url.endswith("abcdefghijk")


@pytest.mark.asyncio
async def test_autonomous_queue_is_disabled_by_default_and_requires_license_confirmation(monkeypatch):
    disabled = AutonomousChannelOrchestrator(
        SimpleNamespace(autonomous_channel_enabled=False, autonomous_pexels_license_confirmed=False)
    )
    disabled_result = await disabled.produce_video(_idea())
    assert disabled_result["status"] == "AWAITING_OPERATOR_CONFIGURATION"

    no_license = AutonomousChannelOrchestrator(
        SimpleNamespace(autonomous_channel_enabled=True, autonomous_pexels_license_confirmed=False)
    )
    no_license_result = await no_license.produce_video(_idea())
    assert no_license_result["status"] == "AWAITING_LICENSE_CONFIRMATION"


@pytest.mark.asyncio
async def test_queueing_is_idempotent_and_never_grants_repeat_use_or_uploads(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.projects = {}
            self.pending = []
            self.closed = False
            self.next_id = 1

        def scalar(self, statement):
            entity = statement.column_descriptions[0].get("entity")
            if entity is VideoProject:
                project_key = statement.compile().params.get("project_key_1")
                return self.projects.get(project_key)
            return len(self.projects)

        def add(self, value):
            self.pending.append(value)

        def commit(self):
            for project in self.pending:
                project.id = self.next_id
                self.next_id += 1
                self.projects[project.project_key] = project
            self.pending.clear()

        def refresh(self, _value):
            return None

        def rollback(self):
            self.pending.clear()

        def close(self):
            self.closed = True

    session = FakeSession()
    monkeypatch.setattr(orchestrator_module, "SessionLocal", lambda: session)
    orchestrator = AutonomousChannelOrchestrator(
        SimpleNamespace(
            autonomous_channel_enabled=True,
            autonomous_pexels_license_confirmed=True,
            autonomous_daily_project_limit=3,
        )
    )

    first = await orchestrator.produce_video(_idea())
    second = await orchestrator.produce_video(_idea())

    assert first["status"] == "QUEUED_FOR_PRODUCTION"
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert len(session.projects) == 1
    project = next(iter(session.projects.values()))
    assert project.status == "queued"
    assert project.confirm_pexels_license is True
    assert project.confirm_pexels_repeat_use is False
    assert first["publication"] == "requires existing VyralX rights checks and operator approval"
    assert session.closed is True


def test_orchestrator_has_no_direct_upload_or_placeholder_render_path():
    import inspect

    source = inspect.getsource(orchestrator_module.AutonomousChannelOrchestrator)
    assert "upload_video(" not in source
    assert "For now, return a placeholder path" not in source
    assert "SessionLocal()" in source
    assert "QUEUED_FOR_PRODUCTION" in source
