"""Small timeout-bounded clients for optional FRIDAY Universe integrations.

Endpoint paths are explicit arguments because the peer APIs can evolve
independently. No agent API is called unless its base URL and key are configured.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings


@dataclass(frozen=True)
class Peer:
    name: str
    base_url: str
    api_key: str


def configured_peers() -> dict[str, Peer]:
    settings = get_settings()
    candidates = {
        "friday": (settings.friday_url, settings.friday_api_key),
        "inference": (settings.inference_url, settings.inference_api_key),
        "intelx": (settings.intelx_url, settings.intelx_api_key),
        "memora": (settings.memora_url, settings.memora_api_key),
        "sentinel": (settings.sentinel_url, settings.sentinel_api_key),
    }
    return {
        name: Peer(name=name, base_url=url.rstrip("/"), api_key=key)
        for name, (url, key) in candidates.items()
        if url.strip() and key.strip()
    }


def peer_health(name: str, *, timeout_seconds: float = 3.0) -> dict[str, Any]:
    peers = configured_peers()
    peer = peers.get(name)
    if peer is None:
        return {"name": name, "configured": False, "reachable": False, "status": "not_configured"}
    headers = {"Authorization": f"Bearer {peer.api_key}", "X-API-Key": peer.api_key}
    try:
        response = httpx.get(f"{peer.base_url}/health", headers=headers, timeout=timeout_seconds)
        return {
            "name": name,
            "configured": True,
            "reachable": response.is_success,
            "http_status": response.status_code,
            "status": "ok" if response.is_success else "unhealthy",
        }
    except httpx.RequestError as exc:
        return {
            "name": name,
            "configured": True,
            "reachable": False,
            "status": "unreachable",
            "error_type": type(exc).__name__,
        }


def post_peer_json(
    name: str,
    path: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    """Call an explicitly configured peer endpoint; do not follow arbitrary redirects."""
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("Peer endpoint path must be an absolute path")
    if "://" in path or ".." in path:
        raise ValueError("Peer endpoint path must not be a URL or traversal path")
    peer = configured_peers().get(name)
    if peer is None:
        raise RuntimeError(f"FRIDAY peer {name!r} is not configured")
    try:
        response = httpx.post(
            peer.base_url + path,
            headers={"Authorization": f"Bearer {peer.api_key}", "X-API-Key": peer.api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=timeout_seconds,
            follow_redirects=False,
        )
        response.raise_for_status()
        if not response.content:
            return {}
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"FRIDAY peer {name!r} returned a non-object response")
        return data
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"FRIDAY peer {name!r} returned HTTP {exc.response.status_code}") from None
    except httpx.RequestError as exc:
        raise RuntimeError(f"FRIDAY peer {name!r} request failed ({type(exc).__name__})") from None
