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
    if settings.app_env.lower() in ("development", "test") and (
        not x_api_key and not authorization and not x_friday_api_key
    ):
        return

    bearer = ""
    if authorization:
        scheme, separator, value = authorization.partition(" ")
        if separator and scheme.lower() == "bearer":
            bearer = value.strip()
    supplied = x_friday_api_key or x_api_key or bearer
    valid_keys = [
        k
        for k in (
            settings.api_key,
            getattr(settings, "vyralx_api_key", ""),
            getattr(settings, "friday_api_key", ""),
        )
        if k and (settings.app_env.lower() not in ("production", "prod") or k != "development-only-change-me")
    ]
    if not supplied or not any(secrets.compare_digest(supplied, vk) for vk in valid_keys):
        raise HTTPException(status_code=401, detail="Valid Bearer token, X-FRIDAY-API-Key, or X-API-Key required")
