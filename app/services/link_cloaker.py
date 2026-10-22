"""VyralX Link Cloaker & UTM Attribution Engine.

Appends platform-specific UTM tracking parameters and generates clean,
high-trust redirect links for maximum affiliate click-through rate (CTR).
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Any

log = logging.getLogger("vyralx.link_cloaker")

# Clean Vanity Domains / Shortener URL Mapping
VANITY_BASE_URL = "https://vyralx.link"


def generate_tracked_link(
    base_url: str,
    platform: str,
    campaign_id: str,
    medium: str = "short_video",
    content_id: str = "pinned_comment",
) -> str:
    """Append full UTM attribution parameters to any affiliate or product link."""
    parsed = urllib.parse.urlparse(base_url)
    existing_params = urllib.parse.parse_qs(parsed.query)

    new_params = {
        "utm_source": [platform.lower()],
        "utm_medium": [medium],
        "utm_campaign": [campaign_id.lower()],
        "utm_content": [content_id.lower()],
    }

    # Merge parameters without overriding essential affiliate tags
    for k, v in existing_params.items():
        if k not in new_params:
            new_params[k] = v

    encoded_query = urllib.parse.urlencode(new_params, doseq=True)
    tracked_url = urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        encoded_query,
        parsed.fragment,
    ))
    return tracked_url


def create_vanity_slug(offer_slug: str, video_id: str) -> str:
    """Generate high-trust branded short link representation (e.g. vyralx.link/optics-8kgg)."""
    clean_slug = offer_slug.lower().replace(" ", "-")[:12]
    clean_vid = video_id.replace("-", "")[:6]
    return f"{VANITY_BASE_URL}/{clean_slug}-{clean_vid}"


def calculate_projected_earnings(
    monthly_views: int,
    average_ctr: float = 0.015,  # 1.5% click-through on pinned comment
    conversion_rate: float = 0.03,  # 3% buyer conversion on landing page
    average_commission: float = 12.50,  # $12.50 average payout per conversion
    cpm_ad_rate: float = 0.12,  # $0.12 YouTube Shorts RPM per 1,000 views
) -> dict[str, Any]:
    """Calculate projected monthly earnings across Ad revenue and Affiliate conversions."""
    ad_revenue = (monthly_views / 1000.0) * cpm_ad_rate
    projected_clicks = monthly_views * average_ctr
    projected_conversions = projected_clicks * conversion_rate
    affiliate_revenue = projected_conversions * average_commission
    total_projected = ad_revenue + affiliate_revenue

    return {
        "monthly_views": monthly_views,
        "ad_revenue_est_usd": round(ad_revenue, 2),
        "affiliate_clicks_est": int(projected_clicks),
        "affiliate_conversions_est": int(projected_conversions),
        "affiliate_revenue_est_usd": round(affiliate_revenue, 2),
        "total_revenue_est_usd": round(total_projected, 2),
        "rpm_effective_usd": round((total_projected / monthly_views) * 1000.0, 3) if monthly_views > 0 else 0.0,
    }
