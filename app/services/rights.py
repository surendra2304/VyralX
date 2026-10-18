"""Conservative, traceable source-rights checks for video assets."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import Asset, RenderJob, Source


def source_is_publishable(source: Source | None) -> bool:
    """A checkbox alone is not permission: require an explicit claim and evidence reference."""
    if source is None or not bool(source.rights_verified):
        return False
    license_name = str(source.license_name or "").strip()
    evidence = str(source.permission_reference or "").strip()
    if not license_name or not evidence:
        return False
    return True


def verified_render_sources(render: RenderJob, db: Session) -> list[tuple[Asset, Source]]:
    """Resolve every source clip encoded in a render job, not only the primary asset."""
    try:
        options = json.loads(render.options_json or "{}")
    except (TypeError, ValueError):
        raise ValueError("Render has invalid persisted options") from None
    raw_ids = options.get("montage_asset_ids", []) if isinstance(options, dict) else []
    if not isinstance(raw_ids, list):
        raise ValueError("Render montage_asset_ids must be an array")
    asset_ids: list[int] = []
    for raw in raw_ids:
        try:
            asset_id = int(raw)
        except (TypeError, ValueError):
            raise ValueError("Render references an invalid asset ID") from None
        if asset_id > 0 and asset_id not in asset_ids:
            asset_ids.append(asset_id)
    if render.asset_id not in asset_ids:
        asset_ids.insert(0, render.asset_id)
    if not asset_ids or len(asset_ids) > 4:
        raise ValueError("Render must reference between 1 and 4 source assets")

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
    """Preserve Pexels creator/source credits within YouTube's description length limit."""
    lines: list[str] = []
    seen: set[str] = set()
    for _, source in source_records:
        if str(source.platform or "").lower() != "pexels":
            continue
        url = str(source.source_url or "").strip()
        creator = str(source.creator or "Pexels creator").strip()
        key = url or creator
        if key in seen:
            continue
        seen.add(key)
        license_url = str(source.permission_reference or "").strip()
        suffix = f" — License: {license_url[:500]}" if license_url else ""
        line = f"- {creator[:120]} (Pexels): {url[:600]}{suffix}"
        lines.append(line)
    if not lines:
        return description[:limit]
    credit_block = "Stock footage credits:\n" + "\n".join(lines)
    credit_block = credit_block[: max(0, limit - 4)]
    available = max(0, limit - len(credit_block) - 4)
    intro = description.strip()[:available]
    return (intro + "\n\n" + credit_block).strip()[:limit]
