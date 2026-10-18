from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class DiscoveryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    max_results: int = Field(default=10, ge=1, le=25)
    order: Literal["relevance", "date", "viewCount", "rating"] = "viewCount"


class SourceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    source_url: str = Field(default="", max_length=2048)
    platform: str = Field(default="manual", max_length=40)
    creator: str = Field(default="", max_length=300)
    license_name: str = Field(default="", max_length=200)
    permission_reference: str = Field(default="", max_length=2048)
    rights_verified: bool = False
    notes: str = ""


class CaptionSegment(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def validate_time_range(self) -> "CaptionSegment":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Caption end_seconds must be greater than start_seconds")
        return self


class RenderRequest(BaseModel):
    asset_id: int = Field(gt=0)
    preset: str = Field(pattern="^(shorts|long|square)$")
    trim_start_seconds: float = Field(default=0, ge=0)
    trim_end_seconds: float | None = Field(default=None, gt=0)
    fit_mode: Literal["pad", "crop"] = "pad"
    subtitle_segments: list[CaptionSegment] = Field(default_factory=list, max_length=100)
    content_pack_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_trim(self) -> "RenderRequest":
        if self.trim_end_seconds is not None and self.trim_end_seconds <= self.trim_start_seconds:
            raise ValueError("trim_end_seconds must be greater than trim_start_seconds")
        return self


class PublishRequest(BaseModel):
    asset_id: int = Field(gt=0)
    render_job_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    privacy_status: str | None = Field(default=None, pattern="^(private|unlisted|public)$")
    scheduled_at: datetime | None = None
    confirm_rights: bool = False

    @field_validator("scheduled_at")
    @classmethod
    def validate_scheduled_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_at must include a timezone")
        value = value.astimezone(timezone.utc)
        if value <= datetime.now(timezone.utc):
            raise ValueError("scheduled_at must be in the future")
        return value


class ContentGenerationRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    video_format: Literal["shorts", "long"] = "shorts"
    audience: str = Field(default="general audience", max_length=200)
    tone: str = Field(default="clear, energetic and factual", max_length=200)
    target_seconds: int = Field(default=45, ge=15, le=1800)


class RetryJobRequest(BaseModel):
    reason: str = Field(default="operator_retry", max_length=200)


class PexelsSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    max_results: int = Field(default=10, ge=1, le=25)
    orientation: Literal["portrait", "landscape", "square"] = "portrait"


class PexelsImportRequest(BaseModel):
    video_id: int = Field(gt=0)
    video_file_id: int = Field(gt=0)
    title: str = Field(default="", max_length=300)
    confirm_license: bool = False


class ThumbnailRequest(BaseModel):
    render_job_id: int = Field(gt=0)
    timestamp_seconds: float = Field(default=1.0, ge=0)


class PublishResolutionRequest(BaseModel):
    decision: Literal["uploaded", "not_uploaded"]
    youtube_video_id: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def require_video_id_for_uploaded(self) -> "PublishResolutionRequest":
        if self.decision == "uploaded" and not self.youtube_video_id.strip():
            raise ValueError("youtube_video_id is required when decision is uploaded")
        return self



class AgentTaskRequest(BaseModel):
    task_id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=120)
    task_type: Literal[
        "discover.youtube",
        "discover.pexels",
        "content.generate",
        "content.voiceover",
        "project.create",
        "render.create",
        "publish.request",
    ]
    input: dict = Field(default_factory=dict)
    correlation_id: str = Field(default="", max_length=120)


class AgentTaskCancelRequest(BaseModel):
    reason: str = Field(default="cancelled_by_requester", max_length=200)


class ContentVoiceoverRequest(BaseModel):
    content_pack_id: int = Field(gt=0)


class UniverseTaskEnvelope(BaseModel):
    """Canonical FRIDAY Universe task envelope with the backward-compatible fields used by fleet_client."""

    task_id: str = Field(default_factory=lambda: f"task_{uuid4().hex[:12]}", min_length=1, max_length=120)
    trace_id: str = Field(default_factory=lambda: f"trace_{uuid4().hex[:8]}", max_length=120)
    parent_task_id: str | None = Field(default=None, max_length=120)
    request_id: str | None = Field(default=None, max_length=120)
    actor: str = Field(default="operator", max_length=120)
    capability: str = Field(default="general", max_length=120)
    objective: str = Field(default="", max_length=500)
    inputs: dict = Field(default_factory=dict)
    trust_level: str = Field(default="untrusted", max_length=40)
    authorization_context: dict = Field(default_factory=dict)
    deadline: str | None = Field(default=None, max_length=80)
    idempotency_key: str | None = Field(default=None, max_length=160)
    requested_mode: Literal["sync", "async", "background"] = "async"
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    artifacts: list[dict] = Field(default_factory=list, max_length=100)
    findings: list[dict] = Field(default_factory=list, max_length=100)
    errors: list[dict] = Field(default_factory=list, max_length=100)
    final_state: Literal["PENDING", "RUNNING", "SUCCESS", "ERROR", "DEGRADED", "CANCELLED", "BLOCKED"] = "PENDING"
    source_agent: str = Field(default="friday", max_length=120)
    target_agent: str = Field(default="vyralx", max_length=120)
    action: str = Field(default="", max_length=120)
    payload: dict = Field(default_factory=dict)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlation_id: str = Field(default="", max_length=120)
    task_type: str | None = Field(default=None, max_length=120)

    @model_validator(mode="before")
    @classmethod
    def sync_legacy_fields(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if "payload" in data and "inputs" not in data:
            data["inputs"] = data["payload"]
        elif "inputs" in data and "payload" not in data:
            data["payload"] = data["inputs"]
        if "action" in data and not data.get("objective"):
            data["objective"] = data["action"]
        elif "objective" in data and not data.get("action"):
            data["action"] = data["objective"]
        return data


class VideoProjectCreateRequest(BaseModel):
    project_key: str = Field(default_factory=lambda: "project_" + uuid4().hex[:16], pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
    topic: str = Field(default="Trending topic", min_length=3, max_length=500)
    auto_discover_trend: bool = False
    trend_query: str = Field(default="", max_length=200)
    trend_max_results: int = Field(default=10, ge=3, le=25)
    video_format: Literal["shorts", "long"] = "shorts"
    target_seconds: int = Field(default=45, ge=15, le=600)
    audience: str = Field(default="general audience", max_length=200)
    tone: str = Field(default="clear, energetic and factual", max_length=200)
    scene_count: int = Field(default=4, ge=2, le=4)
    confirm_pexels_license: bool = False
    use_voiceover: bool = True


class VideoProjectRetryRequest(BaseModel):
    reason: str = Field(default="operator_retry", max_length=200)
