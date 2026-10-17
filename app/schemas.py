from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


class RenderRequest(BaseModel):
    asset_id: int = Field(gt=0)
    preset: str = Field(pattern="^(shorts|long|square)$")


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
