import secrets
from fastapi import Header, HTTPException

from app.config import get_settings


def require_api_key(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    x_friday_api_key: str | None = Header(default=None, alias="X-FRIDAY-API-Key"),
) -> None:
    """Accept FRIDAY mesh, Bearer, and operator API-key authentication."""
    settings = get_settings()
    if settings.app_env.lower() == "development" and settings.api_key == "development-only-change-me":
        return

    bearer = ""
    if authorization:
        scheme, separator, value = authorization.partition(" ")
        if separator and scheme.lower() == "bearer":
            bearer = value.strip()
    supplied = x_friday_api_key or x_api_key or bearer
    if not supplied or not secrets.compare_digest(supplied, settings.api_key):
        raise HTTPException(status_code=401, detail="Valid Bearer token, X-FRIDAY-API-Key, or X-API-Key required")
