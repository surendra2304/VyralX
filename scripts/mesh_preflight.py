"""Read-only FRIDAY mesh preflight for VyralX deployments.

The default run inspects configuration and peer health only. Optional IntelX and
Memora probes perform authenticated reads; the Inference probe explicitly invokes
content generation and may consume provider quota. This script never writes to peer
services, changes deployment state, or prints credentials or provider response bodies.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Make ``python scripts/mesh_preflight.py`` work from an uninstalled checkout too.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.services.content import generate_content_pack
from app.services.peers import get_peer_json, peer_health

PEER_NAMES = ("friday", "inference", "intelx", "memora", "sentinel")
PROBE_NAMES = ("intelx", "memora")
ERROR_STATES = {"error", "failed", "failure", "rejected", "blocked"}
PRIVATE_MEMORA_NAMESPACE = "memora://vyralx/private"


def _entry(check: str, status: str, message: str, **details: Any) -> dict[str, Any]:
    return {"check": check, "status": status, "message": message, **details}


def _valid_base_url(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip())
        return bool(
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and (parsed.port is None or 1 <= parsed.port <= 65535)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def _collection_items(payload: Any, *, depth: int = 0) -> list | None:
    """Unwrap known list envelopes while rejecting explicit provider error envelopes."""
    if depth > 4:
        return None
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return None
    status = str(payload.get("status") or "").strip().casefold()
    if payload.get("error") or payload.get("success") is False or status in ERROR_STATES:
        raise ValueError("provider returned an error envelope")
    for key in ("items", "reports", "memories", "results", "matches"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    for key in ("result", "response", "payload", "data"):
        nested = payload.get(key)
        if isinstance(nested, (dict, list)):
            result = _collection_items(nested, depth=depth + 1)
            if result is not None:
                return result
    # Some valid empty-search APIs only return explicit success/count metadata.
    if payload.get("success") is True or status in {"ok", "success", "completed"}:
        if not any(key in payload for key in ("error", "errors")):
            return []
    return None


def _peer_configuration(settings, name: str) -> tuple[str, str]:
    return str(getattr(settings, f"{name}_url", "") or "").strip(), str(
        getattr(settings, f"{name}_api_key", "") or ""
    ).strip()


def run_preflight(
    *,
    required_peers: set[str] | None = None,
    probes: set[str] | None = None,
    probe_inference: bool = False,
    timeout_seconds: float = 4.0,
) -> dict[str, Any]:
    """Run bounded, read-only checks and return a secret-free report."""
    settings = get_settings()
    required = set(required_peers or ())
    requested_probes = set(probes or ())
    checks: list[dict[str, Any]] = []

    if getattr(settings, "memora_read_enabled", False) or getattr(
        settings, "memora_write_enabled", False
    ):
        required.add("memora")
    required.update(requested_probes)
    if probe_inference:
        required.add("inference")

    for name in PEER_NAMES:
        url, key = _peer_configuration(settings, name)
        is_required = name in required
        if bool(url) != bool(key):
            checks.append(
                _entry(
                    f"{name}.configuration",
                    "failed",
                    "URL and API key must either both be configured or both be empty.",
                    peer=name,
                    required=is_required,
                )
            )
            continue
        if not url:
            checks.append(
                _entry(
                    f"{name}.configuration",
                    "failed" if is_required else "skipped",
                    "Peer is not configured."
                    if is_required
                    else "Optional peer is not configured.",
                    peer=name,
                    required=is_required,
                )
            )
            continue
        if not _valid_base_url(url):
            checks.append(
                _entry(
                    f"{name}.configuration",
                    "failed",
                    "Peer URL must be a valid HTTP(S) base URL without credentials, query, or fragment.",
                    peer=name,
                    required=is_required,
                )
            )
            continue
        try:
            result = peer_health(name, timeout_seconds=min(timeout_seconds, 10.0))
        except Exception as exc:  # Defensive: the report must not echo exception text.
            result = {"status": "probe_error", "error_type": type(exc).__name__}
        reachable = result.get("status") == "ok" and result.get("reachable") is True
        status = "ok" if reachable else ("failed" if is_required else "warning")
        details = {"peer": name, "required": is_required}
        if isinstance(result.get("http_status"), int):
            details["http_status"] = result["http_status"]
        if result.get("error_type"):
            details["error_type"] = str(result["error_type"])[:80]
        checks.append(
            _entry(
                f"{name}.health",
                status,
                "Health endpoint responded successfully; authentication is verified only by active contract probes."
                if reachable
                else (
                    "Required peer health check failed."
                    if is_required
                    else "Optional peer is configured but unhealthy."
                ),
                **details,
            )
        )

    for name in sorted(requested_probes):
        try:
            if name == "intelx":
                payload = get_peer_json(
                    "intelx",
                    "/api/v1/research/query",
                    {"sector": "vyralx deployment preflight", "limit": 1},
                    timeout_seconds=timeout_seconds,
                )
                items = _collection_items(payload)
                message = "Authenticated IntelX research query returned a valid response."
            elif name == "memora":
                payload = get_peer_json(
                    "memora",
                    "/v1/memories/search",
                    {
                        "q": "vyralx deployment preflight",
                        "namespace_path": PRIVATE_MEMORA_NAMESPACE,
                        "limit": 1,
                        "min_score": 0.0,
                    },
                    timeout_seconds=timeout_seconds,
                )
                items = _collection_items(payload)
                message = "Authenticated, read-only Memora search returned a valid response."
            else:  # argparse validates choices; this protects callers of run_preflight.
                checks.append(
                    _entry(f"{name}.probe", "failed", "Unsupported probe requested.", peer=name)
                )
                continue
            if items is None:
                raise ValueError("provider response did not match a supported collection envelope")
            checks.append(
                _entry(
                    f"{name}.probe",
                    "ok",
                    message,
                    peer=name,
                    records_returned=len(items),
                    mutating=False,
                )
            )
        except Exception as exc:
            checks.append(
                _entry(
                    f"{name}.probe",
                    "failed",
                    "Active read probe failed; response bodies and credential details were suppressed.",
                    peer=name,
                    error_type=type(exc).__name__,
                    mutating=False,
                )
            )

    if probe_inference:
        try:
            pack = generate_content_pack(
                "VyralX deployment preflight",
                video_format="shorts",
                target_seconds=15,
            )
            if not isinstance(pack, dict) or not pack.get("script"):
                raise ValueError("generation result is missing the validated script")
            checks.append(
                _entry(
                    "inference.generation",
                    "ok",
                    "Authenticated Inference generation returned a schema-validated content pack.",
                    peer="inference",
                    generated_content_discarded=True,
                )
            )
        except Exception as exc:
            checks.append(
                _entry(
                    "inference.generation",
                    "failed",
                    "Active Inference generation probe failed; provider response and generated content were suppressed.",
                    peer="inference",
                    error_type=type(exc).__name__,
                    generated_content_discarded=True,
                )
            )

    if getattr(settings, "sentinel_required_for_publish", False):
        checks.append(
            _entry(
                "sentinel.publish_policy",
                "failed",
                "The documented Sentinel software-review route is not compatible with VyralX's youtube.publish policy contract; keep mandatory Sentinel gating disabled until a dedicated publish-policy endpoint is verified.",
                peer="sentinel",
                required=True,
            )
        )

    statuses = [check["status"] for check in checks]
    overall = (
        "failed"
        if "failed" in statuses
        else "warning"
        if "warning" in statuses or "skipped" in statuses
        else "ok"
    )
    return {
        "service": "vyralx-mesh-preflight",
        "overall_status": overall,
        "read_only": True,
        "checks": checks,
        "summary": {
            "ok": statuses.count("ok"),
            "warning": statuses.count("warning"),
            "failed": statuses.count("failed"),
            "skipped": statuses.count("skipped"),
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-peer",
        action="append",
        choices=PEER_NAMES,
        default=[],
        metavar="PEER",
        help="Fail if this peer is missing or unhealthy. May be specified multiple times.",
    )
    parser.add_argument(
        "--probe",
        action="append",
        choices=PROBE_NAMES,
        default=[],
        metavar="PEER",
        help="Perform an authenticated, read-only contract query for IntelX or Memora.",
    )
    parser.add_argument(
        "--probe-inference",
        action="store_true",
        help="Actively generate and discard a 15-second test content pack; may consume provider quota.",
    )
    parser.add_argument(
        "--timeout", type=float, default=4.0, help="Per-request timeout in seconds (1–60)."
    )
    parser.add_argument("--json", action="store_true", help="Print a machine-readable JSON report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not 1.0 <= args.timeout <= 60.0:
        parser.error("--timeout must be between 1 and 60 seconds")
    report = run_preflight(
        required_peers=set(args.require_peer),
        probes=set(args.probe),
        probe_inference=args.probe_inference,
        timeout_seconds=args.timeout,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"VyralX mesh preflight: {report['overall_status'].upper()}")
        for check in report["checks"]:
            suffix = f" [{check['peer']}]" if check.get("peer") else ""
            detail = f" ({check['http_status']})" if check.get("http_status") else ""
            print(
                f"{check['status'].upper():7} {check['check']}{suffix}: {check['message']}{detail}"
            )
        summary = report["summary"]
        print("Summary: " + ", ".join(f"{key}={value}" for key, value in summary.items()))
    return 1 if report["overall_status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
