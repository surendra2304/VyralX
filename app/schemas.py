from pydantic import BaseModel, Field, HttpUrl


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
    asset_id: int
    preset: str = Field(pattern="^(shorts|long|square)$")


class PublishRequest(BaseModel):
    asset_id: int
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    privacy_status: str = Field(default="private", pattern="^(private|unlisted|public)$")
    scheduled_at: str = ""
    confirm_rights: bool = False
