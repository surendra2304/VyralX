"""Conservative source-rights checks for VyralX assets."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.models import Asset, RenderJob, Source

_PLACEHOLDERS = {"-", "n/a", "na", "none", "unknown", "tbd", "todo", "pending", "not provided"}


def _meaningful(value: str) -> bool:
    normalized = " ".join(value.split()).strip().casefold()
    return (
        len(normalized) >= 5
        and normalized not in _PLACEHOLDERS
        and not normalized.startswith(("replace-with", "your license", "your permission", "todo:", "tbd:"))
    )


def source_is_publishable(source: Source | None) -> bool:
    """Require a meaningful rights record and validate official Pexels provenance."""
    if source is None or not bool(source.rights_verified):
        return False
    license_name = str(source.license_name or "").strip()
    evidence = str(source.permission_reference or "").strip()
    if not _meaningful(license_name) or not _meaningful(evidence):
        return False
    if str(source.platform or "").strip().casefold() == "pexels":
        media = urlsplit(str(source.source_url or "").strip())
        license_url = urlsplit(evidence)
        return (
            license_name.casefold() == "pexels content license"
            and media.scheme == "https"
            and media.hostname in {"pexels.com", "www.pexels.com"}
            and media.path.startswith("/video/")
            and license_url.scheme == "https"
            and license_url.hostname in {"pexels.com", "www.pexels.com"}
            and license_url.path.rstrip("/") == "/license"
        )
    return True


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
    if len(description) > limit:
        raise ValueError("Description exceeds the limit; shorten it before publishing")
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
    available = limit - len(separator) - len(block)
    if available < 0:
        raise ValueError("Required stock attribution exceeds the description limit")
    intro = description[:available].rstrip()
    if len(intro) < len(description) and " " in intro:
        intro = intro[:intro.rfind(" ")].rstrip()
    result = (intro + separator + block).strip()
    if len(block) > limit or len(result) > limit:
        raise ValueError("Required stock attribution exceeds the description limit")
    return result
