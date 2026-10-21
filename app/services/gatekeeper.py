"""Client integration for Gatekeeper, the perimeter security, auth, and mesh gateway of the FRIDAY Universe."""
from __future__ import annotations

import logging
from typing import Any

from app.services.peers import configured_peers, post_peer_json

log = logging.getLogger("vyralx.gatekeeper")


def verify_mesh_authorization(
    token: str,
    action: str,
    *,
    resource: str = "/vyralx",
) -> dict[str, Any]:
    """Verify an incoming token or cross-agent capability with Gatekeeper.
    
    If Gatekeeper is not configured, permits the local request with local token verification.
    """
    if "gatekeeper" not in configured_peers():
        log.debug("Gatekeeper verification skipped (gatekeeper not configured)")
        return {"authorized": True, "source": "local_fallback"}

    payload = {
        "source_agent": "vyralx",
        "token": token,
        "action": action,
        "resource": resource,
    }

    try:
        response = post_peer_json("gatekeeper", "/v1/auth/verify", payload, timeout_seconds=4.0)
        authorized = bool(response.get("authorized") or response.get("valid"))
        log.info("Gatekeeper auth response action=%s authorized=%s", action, authorized)
        return {"authorized": authorized, "details": response}
    except Exception as exc:
        log.warning("Gatekeeper verification failed: %s", exc)
        return {"authorized": False, "error": f"{type(exc).__name__}: {exc}"}
