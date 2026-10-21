from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    source_url: Mapped[str] = mapped_column(String(2048), default="")
    platform: Mapped[str] = mapped_column(String(40), default="manual")
    creator: Mapped[str] = mapped_column(String(300), default="")
    license_name: Mapped[str] = mapped_column(String(200), default="")
    permission_reference: Mapped[str] = mapped_column(String(2048), default="")
    repeat_use_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    repeat_use_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    repeat_use_review_notes: Mapped[str] = mapped_column(Text, default="")
    rights_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(40), default="discovered")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    file_path: Mapped[str] = mapped_column(String(2048))
    duration_seconds: Mapped[float] = mapped_column(default=0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    rights_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RenderJob(Base):
    __tablename__ = "render_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(Integer)
    preset: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="queued")
    output_path: Mapped[str] = mapped_column(String(2048), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    options_json: Mapped[str] = mapped_column(Text, default="{}")
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PublishJob(Base):
    __tablename__ = "publish_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(Integer)
    render_job_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    privacy_status: Mapped[str] = mapped_column(String(20), default="private")
    scheduled_at: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(40), default="pending_approval")
    youtube_video_id: Mapped[str] = mapped_column(String(100), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentPack(Base):
    __tablename__ = "content_packs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(500))
    video_format: Mapped[str] = mapped_column(String(20), default="shorts")
    status: Mapped[str] = mapped_column(String(40), default="generated")
    pack_json: Mapped[str] = mapped_column(Text)
    provider_model: Mapped[str] = mapped_column(String(200), default="")
    voiceover_path: Mapped[str] = mapped_column(String(2048), default="")
    voiceover_status: Mapped[str] = mapped_column(String(40), default="not_generated")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VideoMetric(Base):
    __tablename__ = "video_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    publish_job_id: Mapped[int] = mapped_column(Integer, index=True)
    youtube_video_id: Mapped[str] = mapped_column(String(100), index=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentTask(Base):
    __tablename__ = "agent_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    task_type: Mapped[str] = mapped_column(String(80), index=True)
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    authorization_context_json: Mapped[str] = mapped_column(Text, default="{}")
    correlation_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    trace_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    parent_task_id: Mapped[str] = mapped_column(String(120), default="")
    request_id: Mapped[str] = mapped_column(String(120), default="")
    actor: Mapped[str] = mapped_column(String(120), default="operator")
    capability: Mapped[str] = mapped_column(String(120), default="")
    objective: Mapped[str] = mapped_column(String(500), default="")
    trust_level: Mapped[str] = mapped_column(String(40), default="untrusted")
    deadline: Mapped[str] = mapped_column(String(80), default="")
    requested_mode: Mapped[str] = mapped_column(String(20), default="async")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    source_agent: Mapped[str] = mapped_column(String(120), default="friday")
    target_agent: Mapped[str] = mapped_column(String(120), default="vyralx")
    action: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VideoProject(Base):
    __tablename__ = "video_projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    topic: Mapped[str] = mapped_column(String(500))
    auto_discover_trend: Mapped[bool] = mapped_column(Boolean, default=False)
    trend_query: Mapped[str] = mapped_column(String(200), default="")
    trend_max_results: Mapped[int] = mapped_column(Integer, default=10)
    trend_source_video_id: Mapped[str] = mapped_column(String(100), default="")
    trend_source_url: Mapped[str] = mapped_column(String(2048), default="")
    trend_score: Mapped[float] = mapped_column(Float, default=0.0)
    video_format: Mapped[str] = mapped_column(String(20), default="shorts")
    target_seconds: Mapped[int] = mapped_column(Integer, default=45)
    audience: Mapped[str] = mapped_column(String(200), default="general audience")
    tone: Mapped[str] = mapped_column(String(200), default="clear, energetic and factual")
    scene_count: Mapped[int] = mapped_column(Integer, default=4)
    confirm_pexels_license: Mapped[bool] = mapped_column(Boolean, default=False)
    confirm_pexels_repeat_use: Mapped[bool] = mapped_column(Boolean, default=False)
    use_voiceover: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    content_pack_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    render_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primary_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail_path: Mapped[str] = mapped_column(String(2048), default="")
    memora_memory_id: Mapped[str] = mapped_column(String(128), default="")
    memora_memory_status: Mapped[str] = mapped_column(String(32), default="disabled")
    asset_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# Canonical alias for compatibility
Project = VideoProject
