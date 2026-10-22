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
    repeat_use_allowed: bool = False
    repeat_use_review_notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_repeat_use_review(self) -> "SourceCreate":
        if self.repeat_use_allowed:
            if not self.rights_verified:
                raise ValueError("Repeat-use permission requires verified rights")
            if len(self.license_name.strip()) < 5 or len(self.permission_reference.strip()) < 5:
                raise ValueError("Repeat-use permission requires a license name and evidence reference")
            if len(self.repeat_use_review_notes.strip()) < 10:
                raise ValueError("Repeat-use permission requires a review note of at least 10 characters")
        return self


class RepeatUseReviewRequest(BaseModel):
    repeat_use_allowed: bool
    review_notes: str = Field(min_length=10, max_length=1000)

    @field_validator("review_notes")
    @classmethod
    def normalize_review_notes(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 10:
            raise ValueError("review_notes must contain at least 10 non-whitespace characters")
        return normalized


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

    @field_validator("title")
    @classmethod
    def validate_youtube_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("YouTube title must not be blank")
        if "<" in value or ">" in value:
            raise ValueError("YouTube title cannot contain '<' or '>'")
        return value

    @field_validator("description")
    @classmethod
    def validate_youtube_description(cls, value: str) -> str:
        if "<" in value or ">" in value:
            raise ValueError("YouTube description cannot contain '<' or '>'")
        if len(value.encode("utf-8")) > 5000:
            raise ValueError("YouTube description must not exceed 5000 UTF-8 bytes")
        return value.strip()

    @field_validator("tags")
    @classmethod
    def validate_youtube_tags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in values:
            tag = raw.strip()
            key = tag.casefold()
            if not tag or key in seen:
                continue
            seen.add(key)
            cleaned.append(tag)
        # YouTube counts commas between tag items and quotation marks around
        # tags that contain spaces toward the 500-character snippet.tags limit.
        budget = sum(len(tag) + (2 if " " in tag else 0) for tag in cleaned)
        budget += max(0, len(cleaned) - 1)
        if budget > 500:
            raise ValueError("YouTube tags must fit within the 500-character API limit")
        return cleaned

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


class PublishApprovalRequest(BaseModel):
    """Explicit operator acknowledgement required by the publish approval endpoint."""

    confirm_review: bool


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
    confirm_repeat_use: bool = False


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
        if "inputs" in data and "payload" in data and data["inputs"] != data["payload"]:
            raise ValueError("inputs and payload must match when both are provided")
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
    confirm_pexels_repeat_use: bool = False
    use_voiceover: bool = True


class VideoProjectRetryRequest(BaseModel):
    reason: str = Field(default="operator_retry", max_length=200)


class ViralHooksRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=500)
    audience: str = Field(default="general", max_length=200)

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v: str) -> str:
        s = v.strip()
        if len(s) < 2:
            raise ValueError("topic must contain at least 2 non-whitespace characters")
        return s


class StrategyEvaluationRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=500)
    audience: str = Field(default="general audience", max_length=200)
    tone: str = Field(default="clear, energetic and factual", max_length=200)
    pillars: list[str] = Field(default_factory=list)

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v: str) -> str:
        s = v.strip()
        if len(s) < 2:
            raise ValueError("topic must contain at least 2 non-whitespace characters")
        return s


class DistributionPackageRequest(BaseModel):
    hook_text: str | None = Field(default=None, max_length=300)
    niche: str = Field(default="technology", max_length=100)
