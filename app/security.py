import secrets
from fastapi import Header, HTTPException
from app.config import get_settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if settings.app_env == "development" and settings.api_key == "development-only-change-me":
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Valid X-API-Key required")
