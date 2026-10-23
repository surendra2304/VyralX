"""Script to re-edit all viral videos with genre-adapted subtitles and high-CTR thumbnails.

Strictly local rendering: DOES NOT UPLOAD ANY VIDEO TO YOUTUBE.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.services.algorithm_booster import render_dual_screen_retention_short
from app.services.multiplatform_publisher import package_multiplatform_release
from app.services.thumbnail_designer import generate_genre_thumbnail
from app.services.video_styler import render_adaptive_short

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vyralx.reedit")

ARTIFACT_DIR = Path(r"C:\Users\Surendra\.gemini\antigravity\brain\9eb461ef-8e8c-48bb-9abe-936c30ea157d")
RENDERS_DIR = Path("renders")
RENDERS_DIR.mkdir(parents=True, exist_ok=True)
BGM_DIR = Path("media/music")

VIRAL_CATALOG = [
    {
        "id": "8kggT2ej-lo",
        "title": "Cheetah Purrs Like A Ferrari Engine",
        "genre": "WILDLIFE",
        "views": 1_060_000_000,
        "headline": "HE DID NOT FLINCH",
        "hook": "DO NOT RUN",
    },
    {
        "id": "sOZrJUkCLYU",
        "title": "Wait For The Unexpected Twist",
        "genre": "VIRAL",
        "views": 749_000_000,
        "headline": "WAIT FOR IT",
        "hook": "WAIT FOR THE TWIST",
    },
    {
        "id": "k--pkJcePTM",
        "title": "Do Not Try This Stunt At Home",
        "genre": "VIRAL",
        "views": 578_000_000,
        "headline": "DO NOT TRY THIS",
        "hook": "1 IN A MILLION",
    },
    {
        "id": "A_Q2qpbHrqo",
        "title": "9,999,999 Dollar Sir Negotiation",
        "genre": "VIRAL",
        "views": 478_000_000,
        "headline": "9,999,999$ SIR",
        "hook": "BEST NEGOTIATION EVER",
    },
    {
        "id": "bS_CSAPHjUY",
        "title": "Genius Bushcraft Survival Life Hack",
        "genre": "LIFEHACKS",
        "views": 318_000_000,
        "headline": "THIS SAVES LIVES",
        "hook": "GENIUS SURVIVAL HACK",
    },
    {
        "id": "BmW5Qb3fqlk",
        "title": "That One Golibaaz Friend We All Have",
        "genre": "COMEDY",
        "views": 287_000_000,
        "headline": "THAT ONE FRIEND",
        "hook": "BRO DID NOT HESITATE",
    },
    {
        "id": "JjuQ2ink05Q",
        "title": "Most Satisfying Moments On The Internet",
        "genre": "VIRAL",
        "views": 200_000_000,
        "headline": "ODDLY SATISFYING",
        "hook": "ODDLY SATISFYING",
    },
    {
        "id": "hx265ujsLVU",
        "title": "Pure Chaos Caught On Camera",
        "genre": "VIRAL",
        "views": 162_000_000,
        "headline": "WHAT JUST HAPPENED",
        "hook": "PURE CHAOS",
    },
    {
        "id": "mHE8rDhCWAw",
        "title": "Pure Sportsmanship That Melted Hearts",
        "genre": "SPORTS",
        "views": 135_000_000,
        "headline": "TRUE SPORTSMANSHIP",
        "hook": "PURE RESPECT",
    },
    {
        "id": "heI4DLab-l8",
        "title": "School Relatable Moments We All Remember",
        "genre": "COMEDY",
        "views": 111_000_000,
        "headline": "EVERY STUDENT EVER",
        "hook": "WE ALL DID THIS",
    },
]


def run_reedit_all():
    log.info("Starting complete re-editing of all viral videos and thumbnails...")
    bgm_tracks = list(BGM_DIR.glob("*.mp3"))

    for idx, item in enumerate(VIRAL_CATALOG):
        vid = item["id"]
        source_file = Path(f"media/viral_sources/{vid}.mp4")
        if not source_file.is_file():
            log.warning("Source file missing for %s", vid)
            continue

        genre = item["genre"]
        rendered_out = RENDERS_DIR / f"vyralx-v2-{vid}.mp4"
        thumb_out = RENDERS_DIR / f"vyralx-v2-{vid}-thumbnail.jpg"
        bgm = bgm_tracks[idx % len(bgm_tracks)] if bgm_tracks else None

        log.info("[%d/%d] Re-editing %s (%s - %s)...", idx + 1, len(VIRAL_CATALOG), vid, genre, item["title"])

        # 1. Render adaptive short with dynamic lower-third subtitles
        render_adaptive_short(
            source_video_path=source_file,
            output_path=rendered_out,
            category=genre,
            custom_hook=item["hook"],
            bgm_path=bgm,
            bgm_volume=0.12,
        )

        # 2. Generate high-CTR custom genre thumbnail
        generate_genre_thumbnail(
            video_path=source_file,
            output_path=thumb_out,
            headline=item["headline"],
            category=genre,
        )

        # 3. Copy to artifact directory
        artifact_vid = ARTIFACT_DIR / f"vyralx-repurpose-{vid}.mp4"
        artifact_thumb = ARTIFACT_DIR / f"vyralx-repurpose-{vid}-thumbnail.jpg"
        shutil.copy2(rendered_out, artifact_vid)
        shutil.copy2(thumb_out, artifact_thumb)

        # 4. Package multi-platform release
        package_multiplatform_release(
            video_path=rendered_out,
            original_title=item["title"],
            category=genre,
            video_id=vid,
            original_views=item["views"],
        )

    # Re-render Dual-Screen Retention Videos
    log.info("Re-rendering Dual-Screen Retention Shorts...")
    broll_gadgets = Path("media/retention_broll/satisfying_gadgets.mp4")
    cheetah_source = Path("media/viral_sources/8kggT2ej-lo.mp4")
    comedy_source = Path("media/viral_sources/BmW5Qb3fqlk.mp4")

    if cheetah_source.is_file() and broll_gadgets.is_file():
        ds_cheetah_out = RENDERS_DIR / "vyralx-dualscreen-cheetah-1B.mp4"
        render_dual_screen_retention_short(
            main_video_path=cheetah_source,
            broll_video_path=broll_gadgets,
            output_path=ds_cheetah_out,
            hook_banner="DO NOT RUN",
            bgm_path=bgm_tracks[0] if bgm_tracks else None,
            bgm_volume=0.12,
            category="WILDLIFE",
        )
        ds_cheetah_thumb = RENDERS_DIR / "vyralx-dualscreen-cheetah-1B-thumbnail.jpg"
        generate_genre_thumbnail(
            video_path=ds_cheetah_out,
            output_path=ds_cheetah_thumb,
            headline="HE DID NOT FLINCH",
            category="WILDLIFE",
        )
        shutil.copy2(ds_cheetah_out, ARTIFACT_DIR / "vyralx-dualscreen-cheetah-1B.mp4")
        shutil.copy2(ds_cheetah_thumb, ARTIFACT_DIR / "vyralx-dualscreen-cheetah-1B-thumbnail.jpg")

    if comedy_source.is_file() and broll_gadgets.is_file():
        ds_comedy_out = RENDERS_DIR / "vyralx-dualscreen-comedy.mp4"
        render_dual_screen_retention_short(
            main_video_path=comedy_source,
            broll_video_path=broll_gadgets,
            output_path=ds_comedy_out,
            hook_banner="THAT ONE FRIEND",
            bgm_path=bgm_tracks[1] if bgm_tracks else None,
            bgm_volume=0.12,
            category="COMEDY",
        )
        ds_comedy_thumb = RENDERS_DIR / "vyralx-dualscreen-comedy-thumbnail.jpg"
        generate_genre_thumbnail(
            video_path=ds_comedy_out,
            output_path=ds_comedy_thumb,
            headline="THAT ONE FRIEND",
            category="COMEDY",
        )
        shutil.copy2(ds_comedy_out, ARTIFACT_DIR / "vyralx-dualscreen-comedy.mp4")
        shutil.copy2(ds_comedy_thumb, ARTIFACT_DIR / "vyralx-dualscreen-comedy-thumbnail.jpg")

    log.info("ALL VIDEOS AND THUMBNAILS RE-EDITED SUCCESSFULLY! (Zero uploads performed)")


if __name__ == "__main__":
    run_reedit_all()
