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
        "render.create",
        "publish.request",
    ]
    input: dict = Field(default_factory=dict)
    correlation_id: str = Field(default="", max_length=120)


class AgentTaskCancelRequest(BaseModel):
    reason: str = Field(default="cancelled_by_requester", max_length=200)
