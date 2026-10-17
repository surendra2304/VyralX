from functools import lru_cache
from pathlib import Path

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
    friday_url: str = ""
    friday_api_key: str = ""
    inference_url: str = ""
    inference_api_key: str = ""
    intelx_url: str = ""
    intelx_api_key: str = ""
    memora_url: str = ""
    memora_api_key: str = ""
    sentinel_url: str = ""
    sentinel_api_key: str = ""
    youtube_client_secrets_file: Path = Path("./secrets/youtube-client-secret.json")
    youtube_token_file: Path = Path("./secrets/youtube-token.json")
    youtube_default_privacy: str = "private"
    youtube_category_id: str = "28"
    youtube_upload_enabled: bool = False
    youtube_analytics_enabled: bool = False

    def prepare_directories(self) -> None:
        for directory in (self.data_dir, self.media_dir, self.render_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.youtube_token_file.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
