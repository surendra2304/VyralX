"""VyralX Multi-Platform Packaging & Cross-Posting Dispatcher.

Exports production-ready distribution packages for:
1. YouTube Shorts (1080x1920 full-bleed vertical, SEO title, tags, monetized description, pinned comment)
2. Instagram Reels (1080x1920, first-fold caption hook, 15 viral hashtags, audio suggestion)
3. TikTok (1080x1920, punchy <150 char caption, fyp hashtags, viral sound cue)
4. Facebook Reels (1080x1920, curiosity title, high-share viral tags)
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.algorithm_booster import get_engagement_catalyst
from app.services.link_cloaker import generate_tracked_link
from app.services.monetization import AFFILIATE_OFFERS_BY_NICHE, DEFAULT_OFFERS
from app.services.seo_optimizer import build_seo_description, generate_optimized_title, generate_seo_tags

log = logging.getLogger("vyralx.multiplatform")


def package_multiplatform_release(
    video_path: Path,
    original_title: str,
    category: str,
    video_id: str,
    original_views: int = 0,
    credit_source: str = "",
) -> dict[str, Any]:
    """Package a rendered viral video with full cross-platform metadata into exports/."""
    settings = get_settings()
    export_base = settings.data_dir / "exports" / f"release_{video_id}"
    export_base.mkdir(parents=True, exist_ok=True)

    # 1. Copy video into release bundle
    target_video_file = export_base / f"{video_id}_final_1080x1920.mp4"
    if not target_video_file.is_file() and video_path.is_file():
        shutil.copy2(video_path, target_video_file)

    # 2. Get high-engagement debate question & offers
    cat_upper = str(category).upper()
    debate_question = get_engagement_catalyst(cat_upper)
    offers = AFFILIATE_OFFERS_BY_NICHE.get(cat_upper, DEFAULT_OFFERS)

    # 3. Create tracked links with UTM tags
    tracked_offers = []
    for off in offers:
        tracked_url = generate_tracked_link(
            base_url=off["url"],
            platform="youtube_shorts",
            campaign_id=f"vyral_{video_id}",
        )
        tracked_offers.append({
            "product": off["product"],
            "url": tracked_url,
            "cta": off["cta"],
            "commission_type": off.get("commission_type", "Affiliate (5-15%)"),
        })

    # 4. YouTube Shorts Metadata
    yt_title = generate_optimized_title(original_title, cat_upper)
    yt_tags = generate_seo_tags(cat_upper)
    yt_description = build_seo_description(
        title=yt_title,
        category=cat_upper,
        debate_question=debate_question,
        affiliate_links=tracked_offers,
        credit_attribution=credit_source,
    )
    primary_offer = tracked_offers[0] if tracked_offers else {"cta": "Check this out", "url": "https://amzn.to/example"}
    yt_pinned_comment = (
        f"📌 {primary_offer['cta']}: {primary_offer['url']}\n\n"
        f"💬 {debate_question}\n\n"
        "🔔 Subscribe to VyralX for daily viral moments!"
    )

    youtube_pkg = {
        "platform": "youtube_shorts",
        "title": yt_title,
        "description": yt_description,
        "tags": yt_tags,
        "pinned_comment": yt_pinned_comment,
        "category_id": "24",  # Entertainment
        "visibility": "public",
        "embeddable": True,
    }

    # 5. Instagram Reels Metadata
    ig_first_fold = f"🔥 {yt_title.split('|')[0].strip()}"[:120]
    ig_hashtags = [f"#{t.replace(' ', '')}" for t in yt_tags[:15]]
    ig_caption = (
        f"{ig_first_fold}\n\n"
        f"{debate_question}\n\n"
        f"Drop your verdict below! 👇\n\n"
        f"🔗 Link in bio for exclusive trending gear!\n\n"
        f"{' '.join(ig_hashtags)}"
    )[:2150]

    instagram_pkg = {
        "platform": "instagram_reels",
        "caption": ig_caption,
        "first_fold": ig_first_fold,
        "hashtags": ig_hashtags,
        "recommended_audio": "Trending Reels Audio / Original Clean Audio",
        "cover_time_ms": 1000,
    }

    # 6. TikTok Metadata
    tt_hashtags = ["#fyp", "#foryou", "#viral", "#trending", f"#{cat_upper.lower()}"]
    tt_caption = f"{yt_title.split('|')[0].strip()} 😱 {' '.join(tt_hashtags)}"[:148]

    tiktok_pkg = {
        "platform": "tiktok",
        "caption": tt_caption,
        "hashtags": tt_hashtags,
        "sound_mode": "Original Audio + Trending Sound",
    }

    # 7. Facebook Reels Metadata
    fb_pkg = {
        "platform": "facebook_reels",
        "title": yt_title,
        "caption": f"{yt_title}\n\n{debate_question}\n\nWhat do you think? 👇",
        "hashtags": ig_hashtags[:8],
    }

    # 8. Master Manifest
    master_manifest = {
        "video_id": video_id,
        "original_views": original_views,
        "category": cat_upper,
        "video_file": str(target_video_file),
        "platforms": {
            "youtube": youtube_pkg,
            "instagram": instagram_pkg,
            "tiktok": tiktok_pkg,
            "facebook": fb_pkg,
        },
        "monetization": {
            "pinned_offer": primary_offer,
            "all_offers": tracked_offers,
            "sponsor_inquiry": "partnerships@vyralx.media",
        },
    }

    manifest_path = export_base / "distribution_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(master_manifest, f, indent=2)

    # Write a quick copy-paste text file for zero-friction manual or copy posting
    quick_copy_path = export_base / "QUICK_POST_COPY.txt"
    with open(quick_copy_path, "w", encoding="utf-8") as f:
        f.write(f"=== YOUTUBE SHORTS ===\nTITLE:\n{yt_title}\n\nPINNED COMMENT:\n{yt_pinned_comment}\n\nDESCRIPTION:\n{yt_description}\n\n")
        f.write(f"=== INSTAGRAM REELS ===\nCAPTION:\n{ig_caption}\n\n")
        f.write(f"=== TIKTOK ===\nCAPTION:\n{tt_caption}\n\n")

    log.info("Successfully packaged multi-platform release bundle in: %s", export_base)
    return master_manifest
