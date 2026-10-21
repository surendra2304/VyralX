"""Client integration for DataX, the central metrics, telemetry, and analytics hub of the FRIDAY Universe."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.services.peers import configured_peers, post_peer_json

log = logging.getLogger("vyralx.datax")


def stream_datax_telemetry(
    metric_type: str,
    measurements: dict[str, Any],
    *,
    project_id: int | None = None,
    correlation_id: str = "",
) -> dict[str, Any]:
    """Stream operational metrics, render benchmarks, or video performance to DataX."""
    settings = get_settings()
    if not getattr(settings, "datax_telemetry_enabled", False) and "datax" not in configured_peers():
        log.debug("DataX telemetry skipped (datax not configured or disabled): %s", metric_type)
        return {"status": "skipped", "reason": "not_configured"}

    payload = {
        "source_agent": "vyralx",
        "metric_type": str(metric_type).strip(),
        "project_id": project_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "measurements": measurements or {},
    }

    try:
        response = post_peer_json("datax", "/v1/telemetry/ingest", payload, timeout_seconds=5.0)
        log.info("Telemetry streamed to DataX metric_type=%s project_id=%s", metric_type, project_id)
        return {"status": "streamed", "response": response}
    except Exception as exc:
        log.warning("DataX telemetry dispatch failed: %s", exc)
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
