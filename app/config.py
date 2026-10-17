from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "VyralX"
    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8010
    log_level: str = "INFO"
    api_key: str = "development-only-change-me"
    database_url: str = "sqlite:///./data/vyralx.db"
    data_dir: Path = Path("./data")
    media_dir: Path = Path("./media")
    render_dir: Path = Path("./renders")
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    max_upload_mb: int = 2048
    max_render_seconds: int = 14400
    max_concurrent_renders: int = 1
    default_shorts_width: int = 1080
    default_shorts_height: int = 1920
    default_long_width: int = 1920
    default_long_height: int = 1080
    worker_required: bool = False
    worker_poll_seconds: float = 2.0
    worker_heartbeat_timeout_seconds: int = 90
    worker_max_attempts: int = 3
    friday_url: str = ""
    friday_api_key: str = ""
    inference_url: str = ""
    inference_api_key: str = ""
    inference_model: str = ""
    inference_generation_path: str = "/v1/chat/completions"
    inference_timeout_seconds: int = 60
    inference_tts_path: str = "/v1/audio/speech"
    inference_tts_model: str = ""
    inference_tts_voice: str = "alloy"
    inference_tts_timeout_seconds: int = 180
    intelx_url: str = ""
    intelx_api_key: str = ""
    memora_url: str = ""
    memora_api_key: str = ""
    sentinel_url: str = ""
    sentinel_api_key: str = ""
    sentinel_required_for_publish: bool = False
    sentinel_policy_path: str = "/api/v1/policy/check"
    pexels_api_key: str = ""
    youtube_data_api_key: str = ""
    youtube_client_secrets_file: Path = Path("./secrets/youtube-client-secret.json")
    youtube_token_file: Path = Path("./secrets/youtube-token.json")
    youtube_default_privacy: str = "private"
    youtube_category_id: str = "28"
    youtube_upload_enabled: bool = False
    youtube_analytics_enabled: bool = False

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if self.app_env.lower() != "development" and (
            not self.api_key or self.api_key == "development-only-change-me"
        ):
            raise ValueError("Set a unique API_KEY outside development")
        if self.worker_poll_seconds < 0.5:
            raise ValueError("WORKER_POLL_SECONDS must be at least 0.5")
        if self.worker_max_attempts < 1:
            raise ValueError("WORKER_MAX_ATTEMPTS must be at least 1")
        if self.youtube_default_privacy not in {"private", "unlisted", "public"}:
            raise ValueError("YOUTUBE_DEFAULT_PRIVACY must be private, unlisted, or public")
        if self.sentinel_required_for_publish and not (
            self.sentinel_url and self.sentinel_api_key
        ):
            raise ValueError("SENTINEL_URL and SENTINEL_API_KEY are required when policy checks are enforced")
        return self

    def prepare_directories(self) -> None:
        for directory in (self.data_dir, self.media_dir, self.render_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.youtube_token_file.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
