"""VyralX Raw Viral Video Auto-Publisher.

Uploads original popular viral videos with ZERO editing (no voiceover, no BGM, no subtitles),
using top-tier viral titles, engagement descriptions, and high-volume SEO search tags.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vyralx.raw_uploader")

from app.services.seo_optimizer import build_seo_description, generate_seo_tags
from app.services.youtube import upload_video

RAW_VIRAL_UPLOADS = [
    {
        "id": "8kggT2ej-lo",
        "file": "media/viral_sources/8kggT2ej-lo.mp4",
        "title": "Cheetah Purrs Like A Ferrari Engine 😱 | Nature Is Unreal #Shorts",
        "category_id": "24",  # Entertainment
        "category_name": "WILDLIFE",
        "debate_question": "Would you pet a wild cheetah if you had the chance? YES or NO? 🐆👇",
    },
    {
        "id": "sOZrJUkCLYU",
        "file": "media/viral_sources/sOZrJUkCLYU.mp4",
        "title": "Wait For The Unexpected Twist 😱 | You Won't Believe This #Shorts",
        "category_id": "24",
        "category_name": "VIRAL",
        "debate_question": "Did you see that plot twist coming? Be honest! 🤯👇",
    },
    {
        "id": "k--pkJcePTM",
        "file": "media/viral_sources/k--pkJcePTM.mp4",
        "title": "Do Not Try This Stunt At Home ⚠️ | Millimeter Perfect #Shorts",
        "category_id": "24",
        "category_name": "VIRAL",
        "debate_question": "Rate this insane stunt from 1 to 10! 🔥👇",
    },
    {
        "id": "A_Q2qpbHrqo",
        "file": "media/viral_sources/A_Q2qpbHrqo.mp4",
        "title": "9,999,999 Dollar Sir Negotiation 💀 | Best Counter Offer #Shorts",
        "category_id": "24",
        "category_name": "VIRAL",
        "debate_question": "Who had the better comeback here? 😂👇",
    },
    {
        "id": "bS_CSAPHjUY",
        "file": "media/viral_sources/bS_CSAPHjUY.mp4",
        "title": "Genius Bushcraft Survival Life Hack 🏕️ | This Saves Lives #Shorts",
        "category_id": "24",
        "category_name": "LIFEHACKS",
        "debate_question": "What is the single most useful life hack you've ever learned? 👇",
    },
    {
        "id": "BmW5Qb3fqlk",
        "file": "media/viral_sources/BmW5Qb3fqlk.mp4",
        "title": "That One Golibaaz Friend We All Have 💀😂 | Pure Comedy #Shorts",
        "category_id": "24",
        "category_name": "COMEDY",
        "debate_question": "Tag that ONE friend who tells the craziest fake stories 😭👇",
    },
    {
        "id": "JjuQ2ink05Q",
        "file": "media/viral_sources/JjuQ2ink05Q.mp4",
        "title": "Most Satisfying Moments On The Internet 🤤✨ | 100% Oddly Satisfying #Shorts",
        "category_id": "24",
        "category_name": "VIRAL",
        "debate_question": "How many times did you replay this? Be honest! 👇",
    },
    {
        "id": "hx265ujsLVU",
        "file": "media/viral_sources/hx265ujsLVU.mp4",
        "title": "Pure Chaos Caught On Camera 😱 | What Just Happened?! #Shorts",
        "category_id": "24",
        "category_name": "VIRAL",
        "debate_question": "What would you do if this happened right in front of you? 😱👇",
    },
    {
        "id": "mHE8rDhCWAw",
        "file": "media/viral_sources/mHE8rDhCWAw.mp4",
        "title": "Pure Sportsmanship That Melted Hearts 🤝❤️ | True Respect In Sports #Shorts",
        "category_id": "17",  # Sports
        "category_name": "SPORTS",
        "debate_question": "Is this the greatest sportsmanship moment ever recorded? 🏆👇",
    },
    {
        "id": "heI4DLab-l8",
        "file": "media/viral_sources/heI4DLab-l8.mp4",
        "title": "School Relatable Moments We All Remember 😭 | Every Student Ever #Shorts",
        "category_id": "24",
        "category_name": "COMEDY",
        "debate_question": "Who remembers doing this in class? Relatable or not? 😂👇",
    },
]


def upload_all_raw():
    log.info("Starting unedited popular viral video upload sequence...")
    uploaded_ids = []

    for idx, item in enumerate(RAW_VIRAL_UPLOADS):
        vpath = Path(item["file"])
        if not vpath.is_file():
            log.warning("File missing: %s", vpath)
            continue

        cat = item["category_name"]
        title = item["title"]
        question = item["debate_question"]
        tags = generate_seo_tags(cat)
        desc = build_seo_description(
            title=title,
            category=cat,
            debate_question=question,
            affiliate_links=[],
            credit_attribution="Curated viral clip uploaded for transformative commentary and entertainment.",
        )

        log.info("[%d/%d] Uploading RAW video: %s ('%s')...", idx + 1, len(RAW_VIRAL_UPLOADS), vpath.name, title)
        try:
            yt_id = upload_video(
                file_path=str(vpath),
                title=title,
                description=desc,
                tags=tags,
                privacy_status="public",
                category_id=item["category_id"],
            )
            log.info("PUBLISHED! Watch link: https://youtu.be/%s", yt_id)
            uploaded_ids.append(yt_id)
            time.sleep(3)
        except Exception as e:
            log.error("Upload failed for %s: %s", vpath.name, e)
            break

    log.info("Finished upload sequence. Total published: %d", len(uploaded_ids))
    return uploaded_ids


if __name__ == "__main__":
    upload_all_raw()
