"""Sentinel pre-publish security and policy verification audit client."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.media_quality import analyze_media_signals
from app.services.peers import configured_peers, post_peer_json
from app.services.probe import probe_media


logger = logging.getLogger("vyralx.sentinel")


def compute_provenance_hash(path: str | Path) -> str:
    """Compute cryptographic SHA-256 provenance hash for an auditable media asset."""
    target = Path(path).resolve()
    if not target.is_file() or target.stat().st_size <= 0:
        raise ValueError(f"Media asset does not exist or is empty: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    return compute_provenance_hash(path)


def verify_render_publish_policy(
    *,
    job_id: int,
    asset_id: int,
    render_job_id: int,
    title: str,
    description: str = "",
    privacy_status: str = "private",
    scheduled_at: str = "",
    operator_review_acknowledged: bool = True,
    rights_verified: bool = True,
    render_path: str | Path,
    signal_analysis: dict[str, Any] | None = None,
    render_sources: list[tuple[Any, Any]] | None = None,
) -> dict[str, Any]:
    """Dispatch final render metadata and QA signal scans to Sentinel for pre-publish policy verification.

    Fail-Closed Policy:
    If Sentinel denies the request, or is unreachable when required, publication is strictly blocked.
    """
    settings = get_settings()
    render_file = Path(render_path).resolve()
    if not render_file.is_file() or render_file.stat().st_size <= 0:
        raise ValueError("Render file is missing or empty")

    file_size = render_file.stat().st_size
    file_hash = _file_sha256(render_file)
    metadata = probe_media(render_file)
    actual_duration = float(metadata.get("duration_seconds") or 0.0)
    audio_stream_count = int(metadata.get("audio_stream_count") or 0)
    width = int(metadata.get("width") or 0)
    height = int(metadata.get("height") or 0)

    # If signal analysis wasn't provided, run it now to inspect audio loudness, black frames, silence
    if signal_analysis is None:
        signal_analysis = analyze_media_signals(
            render_file,
            ffmpeg_bin=settings.ffmpeg_bin,
            actual_duration=actual_duration,
            audio_stream_count=audio_stream_count,
            timeout_seconds=max(30, int(actual_duration * 2 + 15)),
        )

    # Quality Gate Standards:
    # 1. Audio loudness scanning (-14 LUFS standard)
    audio_metrics = signal_analysis.get("audio_metrics") or {}
    integrated_loudness = audio_metrics.get("integrated_loudness_lufs")
    loudness_target = getattr(settings, "render_audio_loudness_target_lufs", -14.0)
    min_loudness = getattr(settings, "render_audio_loudness_min_lufs", -24.0)
    max_loudness = getattr(settings, "render_audio_loudness_max_lufs", -10.0)

    loudness_pass = True
    if audio_stream_count > 0:
        if integrated_loudness is None:
            loudness_pass = False
        else:
            loudness_pass = min_loudness <= float(integrated_loudness) <= max_loudness

    # 2. Black frames detection (no black intervals >= 0.5s)
    black_intervals = signal_analysis.get("black_intervals") or []
    black_frames_pass = len(black_intervals) == 0

    # 3. Silence gaps detection (no long silence gap)
    silence_intervals = signal_analysis.get("silence_intervals") or []
    silence_threshold = max(2.0, actual_duration * 0.08)
    long_silence = [
        s for s in silence_intervals
        if float(s.get("duration_seconds") or 0.0) > silence_threshold
    ]
    silence_gaps_pass = len(long_silence) == 0

    overall_quality_pass = loudness_pass and black_frames_pass and silence_gaps_pass

    # Media rights verification summary
    sources_summary: list[dict[str, Any]] = []
    if render_sources:
        for source_asset, source_record in render_sources:
            sources_summary.append({
                "asset_id": getattr(source_asset, "id", None),
                "source_id": getattr(source_record, "id", None),
                "title": getattr(source_record, "title", ""),
                "platform": getattr(source_record, "platform", ""),
                "license_name": getattr(source_record, "license_name", ""),
                "rights_verified": bool(
                    getattr(source_asset, "rights_verified", False)
                    and getattr(source_record, "rights_verified", False)
                ),
            })

    audit_payload: dict[str, Any] = {
        "action": "youtube.publish",
        "action_type": "youtube.publish",
        "scope_policy": "vyralx-publish-policy-v1",
        "job_id": job_id,
        "asset_id": asset_id,
        "render_job_id": render_job_id,
        "title": title,
        "description": description[:1000],
        "privacy_status": privacy_status,
        "scheduled_at": scheduled_at or "",
        "operator_review_acknowledged": operator_review_acknowledged,
        "rights_verified": rights_verified,
        "media_metadata": {
            "file_size": file_size,
            "sha256": file_hash,
            "duration_seconds": round(actual_duration, 2),
            "width": width,
            "height": height,
            "aspect_ratio": f"{width}:{height}",
            "audio_stream_count": audio_stream_count,
        },
        "quality_scan": {
            "integrated_loudness_lufs": integrated_loudness,
            "loudness_standard_target_lufs": loudness_target,
            "loudness_pass": loudness_pass,
            "black_frame_count": len(black_intervals),
            "black_frames_pass": black_frames_pass,
            "silence_gap_count": len(silence_intervals),
            "long_silence_count": len(long_silence),
            "silence_gaps_pass": silence_gaps_pass,
            "overall_quality_pass": overall_quality_pass,
        },
        "sources": sources_summary,
    }

    # If Sentinel peer is configured, dispatch to Sentinel
    is_sentinel_configured = "sentinel" in configured_peers()
    if is_sentinel_configured:
        policy_path = settings.sentinel_policy_path or "/v1/security/audit"
        try:
            response = post_peer_json("sentinel", policy_path, audit_payload)
        except Exception as exc:
            if settings.sentinel_required_for_publish:
                raise RuntimeError(
                    f"Sentinel pre-publish audit failed unreachable ({type(exc).__name__}: {exc}); "
                    "publishing blocked fail-closed."
                ) from exc
            logger.warning(
                "Sentinel audit check skipped (non-blocking mode, error: %s)", exc
            )
            return {
                "allowed": True,
                "decision": "allow_unverified",
                "audit_payload": audit_payload,
                "reason": f"Sentinel check skipped: {exc}",
            }

        decision = str(response.get("decision") or "").lower()
        allowed = response.get("allowed") is True or decision in {"allow", "approved"}
        reason = str(response.get("reason") or "")
        if not allowed:
            raise RuntimeError(
                f"Sentinel pre-publish policy verification denied: {reason or 'policy violation'}"
            )
        return {
            "allowed": True,
            "decision": decision or "allow",
            "reason": reason,
            "sentinel_response": response,
            "audit_payload": audit_payload,
        }

    # When Sentinel is required but unconfigured
    if settings.sentinel_required_for_publish:
        raise RuntimeError(
            "Sentinel audit is required for publication but Sentinel peer is not configured."
        )

    # In local development when Sentinel is optional
    return {
        "allowed": True,
        "decision": "local_allow",
        "reason": "Sentinel not configured and not required for publish.",
        "audit_payload": audit_payload,
    }
