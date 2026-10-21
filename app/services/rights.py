"""Conservative source-rights checks for VyralX assets."""
from __future__ import annotations

import json
import posixpath
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, PublishJob, RenderJob, Source

_PLACEHOLDERS = {"-", "n/a", "na", "none", "unknown", "tbd", "todo", "pending", "not provided"}


def _meaningful(value: str) -> bool:
    normalized = " ".join(value.split()).strip().casefold()
    return (
        len(normalized) >= 5
        and normalized not in _PLACEHOLDERS
        and not normalized.startswith(("replace-with", "your license", "your permission", "todo:", "tbd:"))
    )


def _is_official_pexels_url(
    value: str, *, path_prefix: str | None = None, exact_path: str | None = None
) -> bool:
    """Validate Pexels HTTPS authority strictly, including user info, port, and path."""
    try:
        parsed = urlsplit(str(value or "").strip())
        port = parsed.port  # Accessing it rejects malformed numeric ports.
    except ValueError:
        return False

    # Compare the parsed hostname and port independently. Checking only hostname allows
    # credentials and unusual port syntax to sneak into a value intended as provenance.
    if parsed.scheme.casefold() != "https" or parsed.username is not None or parsed.password is not None:
        return False
    if parsed.hostname is None or parsed.hostname.casefold() not in {"pexels.com", "www.pexels.com"}:
        return False
    if port not in (None, 443):
        return False
    if parsed.netloc.endswith(":") or not parsed.netloc:
        return False

    # Pexels URLs are rights evidence. Do not accept dot segments, encoded traversal,
    # backslashes, or ambiguous repeated slashes that a browser/proxy may normalize to
    # a different resource path.
    decoded_path = unquote(parsed.path)
    if not decoded_path.startswith("/") or "\\" in decoded_path:
        return False
    if any(segment in {".", ".."} for segment in decoded_path.split("/")):
        return False
    normalized_path = posixpath.normpath(decoded_path)
    expected_normalized_path = decoded_path.rstrip("/") or "/"
    if normalized_path != expected_normalized_path:
        return False

    if path_prefix is not None:
        if not normalized_path.startswith(path_prefix):
            return False
        remainder = normalized_path[len(path_prefix):]
        if not remainder:
            return False
        if path_prefix == "/video/" and "/" in remainder:
            return False
    if exact_path is not None and normalized_path != exact_path:
        return False
    return True


def source_is_publishable(source: Source | None) -> bool:
    """Require a meaningful rights record and validate official Pexels provenance."""
    if source is None or not bool(source.rights_verified):
        return False
    license_name = str(source.license_name or "").strip()
    evidence = str(source.permission_reference or "").strip()
    if not _meaningful(license_name) or not _meaningful(evidence):
        return False
    if str(source.platform or "").strip().casefold() == "pexels":
        try:
            media_path = urlsplit(str(source.source_url or "").strip()).path.rstrip("/")
        except ValueError:
            return False
        return (
            license_name.casefold() == "pexels content license"
            and _is_official_pexels_url(source.source_url, path_prefix="/video/")
            and media_path != "/video"
            and _is_official_pexels_url(evidence, exact_path="/license")
        )
    return True


def source_reuse_identity(source: Source | None) -> tuple[str, str] | None:
    """Build a stable source identity; strip URL fragments and common tracking parameters."""
    if source is None:
        return None
    raw_url = str(getattr(source, "source_url", "") or "").strip()
    if raw_url:
        parsed = urlsplit(raw_url)
        if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
            scheme = parsed.scheme.lower()
            hostname = parsed.hostname.casefold()
            try:
                port = parsed.port
            except ValueError:
                port = None
            if port and not (scheme == "https" and port == 443) and not (
                scheme == "http" and port == 80
            ):
                hostname = f"{hostname}:{port}"
            path = parsed.path.rstrip("/") or "/"
            tracking = {"fbclid", "gclid", "dclid", "mc_cid", "mc_eid", "ref"}
            query = urlencode(sorted(
                (key, value)
                for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                if key.casefold() not in tracking and not key.casefold().startswith("utm_")
            ))
            return ("url", urlunsplit((scheme, hostname, path, query, "")))
        return ("url", raw_url.split("#", 1)[0].rstrip("/"))
    source_id = getattr(source, "id", None)
    if source_id is None:
        return None
    platform = str(getattr(source, "platform", "unknown") or "unknown").strip().casefold()
    return ("source_id", f"{platform}:{source_id}")


def _render_asset_ids(render: RenderJob) -> list[int]:
    """Extract source assets from old renders without letting corrupt metadata break history checks."""
    ids: list[int] = []
    primary = getattr(render, "asset_id", None)
    if isinstance(primary, int) and not isinstance(primary, bool) and primary > 0:
        ids.append(primary)
    try:
        options = json.loads(getattr(render, "options_json", "{}") or "{}")
    except (TypeError, ValueError):
        options = {}
    raw_ids = options.get("montage_asset_ids", []) if isinstance(options, dict) else []
    if isinstance(raw_ids, list):
        for value in raw_ids:
            if isinstance(value, bool) or isinstance(value, float) and not value.is_integer():
                continue
            try:
                asset_id = int(value)
            except (TypeError, ValueError):
                continue
            if asset_id > 0 and asset_id not in ids:
                ids.append(asset_id)
            if len(ids) >= 8:
                break
    return ids


def find_repeat_use_blockers(
    source_records: list[tuple[Asset, Source]],
    db: Session,
    *,
    exclude_publish_job_id: int | None = None,
) -> list[dict[str, int | str]]:
    """Flag sources seen in an earlier successful upload without explicit repeat-use review.

    The current source's repeat-use decision is an operator attestation backed by its
    recorded license/permission evidence; this helper does not interpret legal terms.
    """
    previously_published: set[tuple[str, str]] = set()
    history = db.scalars(select(PublishJob).where(PublishJob.status == "uploaded")).all()
    for previous in history:
        if exclude_publish_job_id is not None and previous.id == exclude_publish_job_id:
            continue
        render = db.get(RenderJob, previous.render_job_id)
        if render is None:
            continue
        for asset_id in _render_asset_ids(render):
            asset = db.get(Asset, asset_id)
            if asset is None or not asset.source_id:
                continue
            source = db.get(Source, asset.source_id)
            identity = source_reuse_identity(source)
            if identity is not None:
                previously_published.add(identity)

    blockers: list[dict[str, int | str]] = []
    seen: set[tuple[str, str]] = set()
    for asset, source in source_records:
        identity = source_reuse_identity(source)
        if identity is None or identity not in previously_published:
            continue
        repeat_use_approved = (
            bool(getattr(source, "repeat_use_allowed", False))
            and getattr(source, "repeat_use_reviewed_at", None) is not None
            and len(str(getattr(source, "repeat_use_review_notes", "") or "").strip()) >= 10
        )
        if repeat_use_approved or identity in seen:
            continue
        seen.add(identity)
        blockers.append({
            "asset_id": int(asset.id),
            "source_id": int(source.id),
            "title": str(source.title or asset.title)[:300],
            "source_url": str(source.source_url or "")[:2048],
        })
    return blockers


def is_project_scene_publishable(asset: Asset | None, source: Source | None) -> bool:
    """Validate a project's Pexels provenance before using it in a render.

    This is a metadata/evidence check, not a legal ruling about the operator's use.
    """
    return bool(
        asset is not None
        and asset.rights_verified
        and source is not None
        and str(source.platform or "").strip().casefold() == "pexels"
        and source_is_publishable(source)
    )


def verified_render_sources(render: RenderJob, db: Session) -> list[tuple[Asset, Source]]:
    """Resolve every source clip encoded in a render job, not only the primary asset."""
    try:
        options = json.loads(render.options_json or "{}")
    except (TypeError, ValueError):
        raise ValueError("Render has invalid persisted options") from None
    if not isinstance(options, dict):
        raise ValueError("Render options must be a JSON object")
    is_project_render = getattr(render, "project_id", None) is not None
    if is_project_render and "montage_asset_ids" not in options:
        raise ValueError("Project render must include montage_asset_ids")
    raw_ids = options.get("montage_asset_ids", [])
    if not isinstance(raw_ids, list):
        raise ValueError("Render montage_asset_ids must be an array")
    asset_ids: list[int] = []
    for raw in raw_ids:
        # bool is an int subclass, but it is never a valid persisted asset ID.
        if isinstance(raw, bool) or (isinstance(raw, float) and not raw.is_integer()):
            raise ValueError("Render references an invalid asset ID")
        try:
            asset_id = int(raw)
        except (TypeError, ValueError):
            raise ValueError("Render references an invalid asset ID") from None
        if asset_id <= 0:
            raise ValueError("Render references an invalid asset ID")
        if asset_id not in asset_ids:
            asset_ids.append(asset_id)
        if len(asset_ids) > 8:
            raise ValueError("Render must reference between 1 and 8 source assets")

    if is_project_render:
        if not 2 <= len(asset_ids) <= 8:
            raise ValueError("Project render must reference between 2 and 8 source assets")
        if render.asset_id not in asset_ids:
            raise ValueError("Project render must include its primary asset in montage_asset_ids")
    else:
        if render.asset_id not in asset_ids:
            asset_ids.insert(0, render.asset_id)
        if not asset_ids or len(asset_ids) > 8:
            raise ValueError("Render must reference between 1 and 8 source assets")
    verified: list[tuple[Asset, Source]] = []
    for asset_id in asset_ids:
        asset = db.get(Asset, asset_id)
        if asset is None:
            raise ValueError(f"Render source asset {asset_id} is missing")
        source = db.get(Source, asset.source_id) if asset.source_id else None
        if not asset.rights_verified or not source_is_publishable(source):
            raise ValueError(f"Render source asset {asset_id} lacks verified license evidence")
        if source is None:
            raise ValueError(f"Render source asset {asset_id} has no source record")
        verified.append((asset, source))
    return verified


def append_stock_attribution(description: str, source_records: list[tuple[Asset, Source]], limit: int = 5000) -> str:
    """Append complete Pexels credits; never silently truncate a required source or license URL."""
    limit = min(5000, int(limit))
    if limit < 1:
        raise ValueError("Description limit must be positive")
    description = str(description or "").strip()
    if len(description.encode("utf-8")) > limit:
        raise ValueError("Description exceeds the 5000-byte limit; shorten it before publishing")
    lines: list[str] = []
    seen: set[str] = set()
    for _, source in source_records:
        if str(source.platform or "").strip().casefold() != "pexels":
            continue
        url = str(source.source_url or "").strip()
        license_url = str(source.permission_reference or "").strip()
        if not url or not license_url:
            raise ValueError("Pexels attribution requires both a source URL and license reference")
        if url in seen:
            continue
        # Creator metadata is untrusted provider input; normalize whitespace so
        # it cannot inject extra lines into the description's attribution block.
        creator = " ".join(str(source.creator or "Pexels creator").split())[:300] or "Pexels creator"
        credit_line = f"- {creator} (Pexels): {url} — License: {license_url}"
        if credit_line in description:
            seen.add(url)
            continue
        seen.add(url)
        lines.append(credit_line)
    if not lines:
        return description
    heading = "Stock footage credits:"
    if heading in description:
        block = "\n".join(lines)
        separator = "\n" if description.rstrip().endswith(heading) else "\n\n"
    else:
        block = heading + "\n" + "\n".join(lines)
        separator = "\n\n" if description else ""
    separator_bytes = len(separator.encode("utf-8"))
    block_bytes = len(block.encode("utf-8"))
    available_bytes = limit - separator_bytes - block_bytes
    if available_bytes < 0:
        raise ValueError("Required stock attribution exceeds the description limit")
    encoded_intro = description.encode("utf-8")[:available_bytes]
    intro = encoded_intro.decode("utf-8", errors="ignore").rstrip()
    if len(intro) < len(description) and " " in intro:
        intro = intro[:intro.rfind(" ")].rstrip()
    result = (intro + separator + block).strip()
    if block_bytes > limit or len(result.encode("utf-8")) > limit:
        raise ValueError("Required stock attribution exceeds the description limit")
    return result
