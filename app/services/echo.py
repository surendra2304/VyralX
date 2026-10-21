"""Client integration for Echo, the notification and event dispatch specialist of the FRIDAY Universe."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.services.peers import configured_peers, post_peer_json

log = logging.getLogger("vyralx.echo")


def dispatch_echo_notification(
    event_type: str,
    title: str,
    details: dict[str, Any],
    *,
    severity: str = "info",
    correlation_id: str = "",
) -> dict[str, Any]:
    """Dispatch an event or notification to Echo over the FRIDAY peer mesh.
    
    If Echo is not configured or notifications are disabled, logs and returns safely.
    """
    settings = get_settings()
    if not getattr(settings, "echo_notifications_enabled", False) and "echo" not in configured_peers():
        log.debug("Echo notification skipped (echo not configured or disabled): %s", event_type)
        return {"status": "skipped", "reason": "not_configured"}

    payload = {
        "source_agent": "vyralx",
        "event_type": str(event_type).strip(),
        "title": str(title).strip()[:200],
        "severity": severity if severity in {"info", "warning", "error", "critical"} else "info",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
        "details": details or {},
    }

    try:
        response = post_peer_json("echo", "/v1/notifications", payload, timeout_seconds=5.0)
        log.info("Echo notification dispatched event_type=%s title=%s", event_type, title)
        return {"status": "dispatched", "response": response}
    except Exception as exc:
        log.warning("Echo notification dispatch failed: %s", exc)
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
