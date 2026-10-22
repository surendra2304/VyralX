"""VyralX Media Kit & Sponsorship Monetization Generator.

Generates professional brand outreach kits, CPM pricing rate cards,
and sponsor integration pitch decks to monetize high-view Shorts & Reels.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("vyralx.media_kit")

# Standard Industry Rates for Short-Form Video Placements (2026 Benchmarks)
BASE_CPV_RATE = 0.015  # $15 per 1,000 views ($15 CPM / CPV)
DEDICATED_SHORT_RATE = 0.025  # $25 per 1,000 views for dedicated sponsor content


def generate_sponsorship_rate_card(projected_monthly_views: int) -> dict[str, Any]:
    """Calculate professional sponsorship packages based on projected viewership."""
    views_per_video_est = max(projected_monthly_views // 30, 25000)

    # 1. Standard Pinned Comment + Description Sponsor Link
    pinned_sponsor_tier = {
        "tier_name": "Tier 1: Pinned Comment & Description Placement",
        "deliverables": [
            "Exclusive top pinned comment sponsor link on 5 new Shorts",
            "Top 3 lines in YouTube description with tracked promo link",
            "1x Community Tab shoutout",
        ],
        "projected_impressions": views_per_video_est * 5,
        "rate_usd": max(int((views_per_video_est * 5 / 1000.0) * 8.0), 150),
    }

    # 2. In-Video 3-5 Second Sponsor Callout / Logo Bug
    integrated_sponsor_tier = {
        "tier_name": "Tier 2: In-Video Organic Logo Bug & Callout",
        "deliverables": [
            "Permanent non-intrusive sponsor logo watermark on 5 Shorts",
            "Verbal or text sponsor callout ('Presented by [Brand]')",
            "Exclusive pinned comment & description top link",
            "Cross-post to Instagram Reels and TikTok",
        ],
        "projected_impressions": views_per_video_est * 5,
        "rate_usd": max(int((views_per_video_est * 5 / 1000.0) * BASE_CPV_RATE * 1000.0), 350),
    }

    # 3. Dedicated Custom Brand Story / Product Demo Short
    dedicated_sponsor_tier = {
        "tier_name": "Tier 3: Dedicated Custom Viral Feature",
        "deliverables": [
            "100% dedicated custom high-retention Short centered around product/brand",
            "Hook engineered for 80%+ audience retention",
            "Multi-platform rollout (YouTube Shorts, IG Reels, TikTok)",
            "Whitelisting rights for 30 days for brand paid ads",
        ],
        "projected_impressions": views_per_video_est * 2,
        "rate_usd": max(int((views_per_video_est * 2 / 1000.0) * DEDICATED_SHORT_RATE * 1000.0), 750),
    }

    return {
        "projected_monthly_views": projected_monthly_views,
        "average_views_per_short": views_per_video_est,
        "currency": "USD",
        "packages": [pinned_sponsor_tier, integrated_sponsor_tier, dedicated_sponsor_tier],
    }


def generate_brand_pitch_email(
    brand_name: str,
    brand_product: str,
    target_niche: str = "Viral Tech & Culture",
    projected_views: int = 500000,
) -> str:
    """Generate high-converting cold outreach pitch to sponsor marketing heads."""
    card = generate_sponsorship_rate_card(projected_views)
    avg_views = card["average_views_per_short"]

    pitch = f"""Subject: Partnership with VyralX: Reaching {avg_views:,}+ engaged viewers with {brand_name}

Hi {brand_name} Marketing Team,

I'm reaching out from VyralX (https://vyralx.media), where we curate and produce high-retention viral short-form videos across YouTube Shorts, Instagram Reels, and TikTok, generating over {projected_views:,} monthly impressions in the {target_niche} space.

We love what {brand_name} is building with {brand_product}. Given our high-converting audience of tech-forward, high-intent digital natives (18-34 demographic, 65% US/Tier-1 geography), we would love to feature {brand_name} in an upcoming viral video series.

Our viewers regularly engage with our pinned comments and feature links, driving high-converting referral traffic.

Here is a quick overview of our collaboration formats:
1. Pinned Comment & Description Spotlight: Premium tracked placement on upcoming releases.
2. In-Video Organic Integration: Seamless logo bug and callout integrated into our viral split-screen format.
3. Multi-Platform Bundle: Simultaneous exposure across YouTube Shorts, IG Reels, and TikTok.

Are you open to reviewing our media kit and rate card this week to discuss a trial campaign for {brand_name}?

Best regards,

VyralX Brand Partnerships
partnerships@vyralx.media
https://vyralx.media
"""
    return pitch.strip()
