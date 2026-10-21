"""Client integration for MediaX, the central asset registry and media catalog of the FRIDAY Universe."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.peers import configured_peers, post_peer_json

log = logging.getLogger("vyralx.mediax")


def register_mediax_asset(
    asset_id: int,
    file_path: str | Path,
    metadata: dict[str, Any],
    *,
    media_category: str = "video_render",
    correlation_id: str = "",
) -> dict[str, Any]:
    """Register a local render or media asset with MediaX over the FRIDAY peer mesh.
    
    Provides media fingerprints, duration, format, and provenance metadata.
    """
    settings = get_settings()
    if not getattr(settings, "mediax_registry_enabled", False) and "mediax" not in configured_peers():
        log.debug("MediaX registration skipped (mediax not configured or disabled): asset_id=%s", asset_id)
        return {"status": "skipped", "reason": "not_configured"}

    path = Path(file_path).resolve()
    file_size = path.stat().st_size if path.is_file() else 0

    payload = {
        "source_agent": "vyralx",
        "internal_asset_id": int(asset_id),
        "file_path": str(path),
        "file_size_bytes": file_size,
        "media_category": media_category,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "metadata": metadata or {},
    }

    try:
        response = post_peer_json("mediax", "/v1/assets/register", payload, timeout_seconds=8.0)
        log.info("Asset registered with MediaX asset_id=%s category=%s", asset_id, media_category)
        return {"status": "registered", "response": response}
    except Exception as exc:
        log.warning("MediaX asset registration failed: %s", exc)
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
