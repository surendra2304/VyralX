"""Multi-platform social distribution and metadata packaging engine."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.services.futuris import predict_publish_window
from app.services.sentinel import compute_provenance_hash

log = logging.getLogger("vyralx.distribution")


def format_youtube_metadata(
    title: str,
    description: str,
    tags: list[str],
    *,
    is_short: bool = True,
    attributions: str = "",
) -> dict[str, Any]:
    """Format metadata adhering strictly to YouTube Data API character and tagging bounds."""
    clean_title = " ".join(str(title).strip().split())[:100]
    if is_short and "#Shorts" not in clean_title and len(clean_title) <= 92:
        clean_title = f"{clean_title} #Shorts"

    desc_parts = [description.strip()]
    if attributions:
        desc_parts.append("\n\n--- Stock Footage & Music Attribution ---\n" + attributions.strip())
    
    clean_desc = "\n".join(desc_parts)[:5000]

    clean_tags = []
    total_len = 0
    for t in tags:
        normalized = str(t).strip().replace(",", "")
        if normalized and total_len + len(normalized) + 1 <= 500:
            clean_tags.append(normalized)
            total_len += len(normalized) + 1

    return {
        "platform": "youtube",
        "is_short": is_short,
        "title": clean_title,
        "description": clean_desc,
        "tags": clean_tags,
        "category_id": "28",  # Science & Tech
    }


def format_instagram_reels_metadata(
    topic: str,
    hook_text: str,
    hashtags: list[str] | None = None,
) -> dict[str, Any]:
    """Format caption and hashtag block optimized for Instagram Reels engagement."""
    hook = hook_text.strip()
    clean_topic = topic.strip()

    # First 125 chars appear before the '...more' fold on Instagram Reels
    first_fold = f"🔥 {hook}"[:125]
    body = (
        f"{first_fold}\n\n"
        f"Deep dive into {clean_topic}! Double tap if you learned something new.\n\n"
        f"Comment below your thoughts! 👇"
    )

    tags = hashtags or ["#tech", "#future", "#innovation", "#education", "#shorts", "#reels"]
    caption = f"{body}\n\n{' '.join(tags)}"[:2200]

    return {
        "platform": "instagram_reels",
        "caption": caption,
        "first_fold_hook": first_fold,
        "hashtags": tags[:15],
    }


def format_tiktok_metadata(
    hook_text: str,
    hashtags: list[str] | None = None,
) -> dict[str, Any]:
    """Format short punchy caption optimized for TikTok algorithm."""
    tags = hashtags or ["#fyp", "#viral", "#tech", "#learnontiktok", "#trending"]
    caption = f"{hook_text.strip()} {' '.join(tags)}"[:150]

    return {
        "platform": "tiktok",
        "caption": caption,
        "hashtags": tags[:8],
    }


def generate_distribution_package(
    project_key: str,
    title: str,
    description: str,
    tags: list[str],
    hook_text: str,
    output_dir: str | Path,
    *,
    is_short: bool = True,
    attributions: str = "",
    niche: str = "technology",
    video_path: str | Path | None = None,
    provenance_sha256: str = "",
) -> Path:
    """Generate a distribution manifest JSON bundling all cross-platform metadata and timing."""
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / f"{project_key}-distribution-manifest.json"

    timing = predict_publish_window(niche=niche)

    media_asset_meta = None
    if video_path is not None:
        vp = Path(video_path).resolve()
        hash_val = provenance_sha256
        if not hash_val and vp.is_file():
            try:
                hash_val = compute_provenance_hash(vp)
            except Exception:
                hash_val = ""
        media_asset_meta = {
            "file_path": str(vp),
            "file_size_bytes": vp.stat().st_size if vp.is_file() else 0,
            "sha256": hash_val,
            "provenance_verified": bool(hash_val),
        }

    manifest = {
        "project_key": project_key,
        "generated_for": "VyralX Cross-Platform Studio",
        "optimal_publish_window": timing,
        "media_asset": media_asset_meta,
        "youtube": format_youtube_metadata(title, description, tags, is_short=is_short, attributions=attributions),
        "instagram_reels": format_instagram_reels_metadata(title, hook_text),
        "tiktok": format_tiktok_metadata(hook_text),
    }

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Distribution manifest written to %s", manifest_path)
    return manifest_path
