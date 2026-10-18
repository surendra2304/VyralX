from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "VyralX"
    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    api_key: str = "development-only-change-me"
    database_url: str = "sqlite:///./data/vyralx.db"
    data_dir: Path = Path("./data")
    media_dir: Path = Path("./media")
    render_dir: Path = Path("./renders")
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    max_upload_mb: int = 2048
    max_stock_clip_mb: int = 150
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
    inference_generation_path: str = "/v1/task/execute"
    inference_timeout_seconds: int = 60
    tts_provider: str = "espeak"
    espeak_bin: str = "espeak-ng"
    espeak_voice: str = "en-us"
    espeak_rate: int = 165
    inference_tts_url: str = ""
    inference_tts_api_key: str = ""
    inference_tts_path: str = "/v1/audio/speech"
    inference_tts_model: str = ""
    inference_tts_voice: str = "alloy"
    inference_tts_timeout_seconds: int = 180
    caption_alignment_url: str = ""
    caption_alignment_api_key: str = ""
    caption_alignment_path: str = "/v1/align"
    caption_alignment_timeout_seconds: int = 90
    caption_alignment_language: str = "en"
    intelx_url: str = ""
    intelx_api_key: str = ""
    memora_url: str = ""
    memora_api_key: str = ""
    memora_write_enabled: bool = False
    memora_read_enabled: bool = False
    sentinel_url: str = ""
    sentinel_api_key: str = ""
    sentinel_required_for_publish: bool = False
    sentinel_policy_path: str = ""
    pexels_api_key: str = ""
    youtube_data_api_key: str = ""
    youtube_client_secrets_file: Path = Path("./secrets/youtube-client-secret.json")
    youtube_token_file: Path = Path("./data/secrets/youtube-token.json")
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
        if self.max_stock_clip_mb < 1 or self.max_stock_clip_mb > self.max_upload_mb:
            raise ValueError("MAX_STOCK_CLIP_MB must be between 1 and MAX_UPLOAD_MB")
        if self.tts_provider.lower() not in {"espeak", "external"}:
            raise ValueError("TTS_PROVIDER must be espeak or external")
        if not 80 <= self.espeak_rate <= 300:
            raise ValueError("ESPEAK_RATE must be between 80 and 300")
        if not 1 <= self.caption_alignment_timeout_seconds <= 300:
            raise ValueError("CAPTION_ALIGNMENT_TIMEOUT_SECONDS must be between 1 and 300")
        if (
            not self.caption_alignment_path.startswith("/")
            or self.caption_alignment_path.startswith("//")
            or "?" in self.caption_alignment_path
            or "#" in self.caption_alignment_path
        ):
            raise ValueError("CAPTION_ALIGNMENT_PATH must be a safe absolute path")
        if not self.caption_alignment_language.strip() or len(self.caption_alignment_language) > 20:
            raise ValueError("CAPTION_ALIGNMENT_LANGUAGE must be a short language tag")
        if any(ch.isspace() for ch in self.caption_alignment_language):
            raise ValueError("CAPTION_ALIGNMENT_LANGUAGE must not contain whitespace")
        if self.caption_alignment_url:
            alignment_url = urlsplit(self.caption_alignment_url.strip())
            if (
                alignment_url.scheme not in {"http", "https"}
                or not alignment_url.netloc
                or alignment_url.query
                or alignment_url.fragment
                or alignment_url.username
                or alignment_url.password
            ):
                raise ValueError("CAPTION_ALIGNMENT_URL must be an HTTP(S) base URL without credentials")
            if not self.caption_alignment_api_key.strip():
                raise ValueError("CAPTION_ALIGNMENT_API_KEY is required when alignment is configured")
        if self.youtube_default_privacy not in {"private", "unlisted", "public"}:
            raise ValueError("YOUTUBE_DEFAULT_PRIVACY must be private, unlisted, or public")
        if self.sentinel_required_for_publish and not (
            self.sentinel_url and self.sentinel_api_key
            and self.sentinel_policy_path.startswith("/")
            and not self.sentinel_policy_path.startswith("//")
        ):
            raise ValueError(
                "SENTINEL_URL, SENTINEL_API_KEY and a validated absolute SENTINEL_POLICY_PATH "
                "are required when policy checks are enforced"
            )
        return self

    def prepare_directories(self) -> None:
        for directory in (self.data_dir, self.media_dir, self.render_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.youtube_token_file.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
