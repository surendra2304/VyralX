"""Unit tests for VyralX Monetization, Multi-platform Packaging, SEO, and Growth Engines."""
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.drip_scheduler import compute_next_drip_slots
from app.services.link_cloaker import (
    calculate_projected_earnings,
    create_vanity_slug,
    generate_tracked_link,
)
from app.services.media_kit import (
    generate_brand_pitch_email,
    generate_sponsorship_rate_card,
)
from app.services.monetization import (
    generate_monetized_description,
    generate_monetized_pinned_comment,
)
from app.services.multiplatform_publisher import package_multiplatform_release
from app.services.seo_optimizer import (
    build_seo_description,
    generate_optimized_title,
    generate_seo_tags,
)


class TestMonetizationAndGrowth(unittest.TestCase):
    def test_link_cloaker_and_utm(self):
        base = "https://amzn.to/example-wildlife-optics"
        tracked = generate_tracked_link(base, platform="youtube_shorts", campaign_id="cheetah_1b")
        self.assertIn("utm_source=youtube_shorts", tracked)
        self.assertIn("utm_campaign=cheetah_1b", tracked)
        self.assertIn("utm_medium=short_video", tracked)

        vanity = create_vanity_slug("optics", "8kggT2ej-lo")
        self.assertTrue(vanity.startswith("https://vyralx.link/optics-8kggT2"))

    def test_earnings_projection(self):
        proj = calculate_projected_earnings(monthly_views=1_000_000)
        self.assertEqual(proj["monthly_views"], 1_000_000)
        self.assertGreater(proj["ad_revenue_est_usd"], 0)
        self.assertGreater(proj["affiliate_revenue_est_usd"], 0)
        self.assertGreater(proj["total_revenue_est_usd"], 1000.0)

    def test_seo_optimizer(self):
        title = generate_optimized_title("Baby Cheetah Purrs Like Motor", "WILDLIFE")
        self.assertIn("#Shorts", title)
        self.assertTrue(len(title) <= 100)

        tags = generate_seo_tags("WILDLIFE")
        self.assertTrue(len(tags) >= 5)
        self.assertIn("shorts", tags)

        desc = build_seo_description(
            title="Cheetah Encounter",
            category="WILDLIFE",
            debate_question="Would you pet it?",
            affiliate_links=[{"cta": "Binoculars", "url": "https://vyralx.link/optics"}],
        )
        self.assertIn("QUESTION OF THE DAY:", desc)
        self.assertIn("FEATURED GEAR", desc)
        self.assertIn("Fair Use Notice", desc)

    def test_media_kit_and_brand_deals(self):
        card = generate_sponsorship_rate_card(projected_monthly_views=1_500_000)
        self.assertEqual(len(card["packages"]), 3)
        self.assertGreater(card["packages"][0]["rate_usd"], 100)

        pitch = generate_brand_pitch_email("ApexGear", "Adventure Action Cam", "Wildlife & Extreme Adventure", 1_000_000)
        self.assertIn("ApexGear", pitch)
        self.assertIn("partnerships@vyralx.media", pitch)

    def test_drip_scheduler_slots(self):
        start = datetime(2026, 10, 23, 0, 0, 0, tzinfo=timezone.utc)
        slots = compute_next_drip_slots(count=4, start_time=start)
        self.assertEqual(len(slots), 4)
        for i in range(len(slots) - 1):
            self.assertLess(slots[i], slots[i + 1])

    def test_multiplatform_packager(self):
        with TemporaryDirectory() as tmp_dir:
            dummy_mp4 = Path(tmp_dir) / "test.mp4"
            dummy_mp4.write_bytes(b"dummy_video_stream_bytes")

            pkg = package_multiplatform_release(
                video_path=dummy_mp4,
                original_title="Insane Animal Reaction",
                category="WILDLIFE",
                video_id="testvid123",
                original_views=50_000_000,
            )
            self.assertIn("youtube", pkg["platforms"])
            self.assertIn("instagram", pkg["platforms"])
            self.assertIn("tiktok", pkg["platforms"])
            self.assertIn("facebook", pkg["platforms"])
            self.assertEqual(pkg["video_id"], "testvid123")


if __name__ == "__main__":
    unittest.main()
