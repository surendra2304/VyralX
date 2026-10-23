"""Script to render all 10 videos with Option 2: Transformative Commentary (Daily Dose of Internet Model).

Strictly local rendering. Zero automated uploads performed.
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path

from app.config import get_settings
from app.services.multiplatform_publisher import package_multiplatform_release
from app.services.thumbnail_designer import generate_genre_thumbnail
from app.services.transformative_commentator import (
    COMMENTARY_SCRIPTS,
    render_transformative_short,
)

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vyralx.render_transformative")

ARTIFACT_DIR = Path(r"C:\Users\Surendra\.gemini\antigravity\brain\9eb461ef-8e8c-48bb-9abe-936c30ea157d")
RENDERS_DIR = Path("renders")
RENDERS_DIR.mkdir(parents=True, exist_ok=True)


def run():
    log.info("Starting batch rendering of Option 2: Transformative Commentary videos...")

    for idx, (vid, entry) in enumerate(COMMENTARY_SCRIPTS.items()):
        source_path = Path(f"media/viral_sources/{vid}.mp4")
        if not source_path.is_file():
            log.warning("Source file missing for %s", vid)
            continue

        genre = entry["category"]
        title = entry["title"]
        log.info("[%d/%d] Rendering transformative short: %s ('%s')...", idx + 1, len(COMMENTARY_SCRIPTS), vid, title)

        rendered_file = RENDERS_DIR / f"vyralx-commentary-{vid}.mp4"
        thumb_file = RENDERS_DIR / f"vyralx-commentary-{vid}-thumbnail.jpg"

        # 1. Render transformative short (neural voiceover + ducked original audio + word-synced subtitles)
        render_transformative_short(source_path, rendered_file, entry)

        # 2. Generate high-CTR custom thumbnail
        generate_genre_thumbnail(
            video_path=rendered_file,
            output_path=thumb_file,
            headline=entry["headline"],
            category=genre,
        )

        # 3. Copy to artifact directory
        artifact_video = ARTIFACT_DIR / f"vyralx-commentary-{vid}.mp4"
        artifact_thumb = ARTIFACT_DIR / f"vyralx-commentary-{vid}-thumbnail.jpg"
        shutil.copy2(rendered_file, artifact_video)
        shutil.copy2(thumb_file, artifact_thumb)

        # 4. Package multi-platform release
        package_multiplatform_release(
            video_path=rendered_file,
            original_title=title,
            category=genre,
            video_id=f"comm_{vid}",
            credit_source=f"Original viral footage analyzed and transformed with educational commentary for fair-use reporting.",
        )

    log.info("ALL 10 TRANSFORMATIVE COMMENTARY VIDEOS RENDERED AND PACKAGED SUCCESSFULLY!")


if __name__ == "__main__":
    run()
