"""VyralX SEO & Virality Title/Hook Optimizer.

Generates high-CTR curiosity-gap titles, viral hook banners,
and search-intent tag clusters to maximize algorithmic recommendation & search ranking.
"""
from __future__ import annotations

import logging
import random

log = logging.getLogger("vyralx.seo_optimizer")

# High-converting psychological hook banner templates
VIRAL_HOOK_TEMPLATES: dict[str, list[str]] = {
    "WILDLIFE": [
        "DO NOT RUN 🐆⚠️",
        "WAIT FOR HIS REACTION 😱",
        "HE DID NOT FLINCH 😳",
        "NOBODY EXPECTED THIS 🤯",
        "NATURE IS UNREAL 🔥",
        "HE REALIZED TOO LATE 💀",
    ],
    "LIFEHACKS": [
        "THIS FEELS ILLEGAL TO KNOW 🤯",
        "WHY DON'T THEY TEACH THIS? 🛠️",
        "GENIUS SURVIVAL HACK 🏕️🔥",
        "YOU'VE BEEN DOING THIS WRONG ⚠️",
        "TRY THIS TODAY 💯",
    ],
    "COMEDY": [
        "BRO DID NOT HESITATE 💀😂",
        "HE REGRETTED THIS IMMEDIATELY 😭",
        "WATCH UNTIL THE END 💀",
        "WAIT FOR IT... 😂🔥",
        "NO WAY HE ACTUALLY DID THAT 💀",
    ],
    "SPORTS": [
        "1 IN A MILLION MOMENT 🏆🔥",
        "PURE RESPECT IN SPORTS 🤝❤️",
        "HIS REACTION SAYS EVERYTHING 🥹",
        "INSTANT KARMA OR SKILL? ⚡",
        "LEGENDARY MOVE 💯",
    ],
    "VIRAL": [
        "ONLY 1% OF PEOPLE NOTICE THIS 🧐",
        "WAIT FOR THE PLOT TWIST 😱",
        "THIS BROKE THE INTERNET 🔥",
        "WHAT JUST HAPPENED?! 🤯",
        "WATCH THIS TWICE 🧠",
    ],
}

# High search volume keyword clusters for YouTube SEO & Browse Features
SEO_TAG_CLUSTERS: dict[str, list[str]] = {
    "WILDLIFE": [
        "cheetah encounter", "wild animals", "wildlife moments", "animal instincts",
        "dangerous animals", "nature shorts", "safari clips", "apex predators",
        "animal rescue", "wildlife photography", "nature documentary shorts",
    ],
    "LIFEHACKS": [
        "life hacks", "survival skills", "diy tricks", "useful gadgets",
        "everyday life hacks", "bushcraft tips", "survival tools", "how to hacks",
        "practical tips", "smart tricks",
    ],
    "COMEDY": [
        "funny shorts", "comedy sketches", "funny moments", "instant regret",
        "hilarious reactions", "relatable memes", "humor shorts", "prank gone wrong",
        "best comedy clips", "viral comedy",
    ],
    "SPORTS": [
        "sportsmanship", "respect in sports", "legendary moments", "sports highlights",
        "epic sports moments", "football respect", "athletic skill", "viral sports",
        "emotional moments in sports", "unbelievable sports",
    ],
    "VIRAL": [
        "viral video", "satisfying video", "oddly satisfying", "mindblowing moments",
        "trending shorts", "viral clips 2026", "insane reaction", "internet trending",
        "must watch shorts", "explore page",
    ],
}


def generate_optimized_title(original_title: str, category: str) -> str:
    """Generate high-CTR, algorithm-favored title with emotional triggers & #Shorts."""
    cat = str(category).upper()
    hooks = VIRAL_HOOK_TEMPLATES.get(cat, VIRAL_HOOK_TEMPLATES["VIRAL"])
    hook = random.choice(hooks).replace("⚠️", "").replace("💀", "").replace("🔥", "").strip()

    # Clean original title
    clean_orig = original_title.split("|")[0].split("-")[0].strip()
    if len(clean_orig) > 45:
        clean_orig = clean_orig[:45].rstrip()

    # Combine hook + cleaned original
    candidate = f"{clean_orig} 😱 | {hook} #Shorts"
    if len(candidate) > 95:
        candidate = f"{hook} 😱 #Shorts"

    return candidate


def generate_seo_tags(category: str, base_tags: list[str] | None = None) -> list[str]:
    """Generate up to 500 characters of high-relevance search tags."""
    cat = str(category).upper()
    cluster = SEO_TAG_CLUSTERS.get(cat, SEO_TAG_CLUSTERS["VIRAL"])
    base = base_tags or ["shorts", "viral", "trending", "youtube shorts", "fyp"]

    combined = list(dict.fromkeys(base + cluster))
    final_tags = []
    total_len = 0
    for tag in combined:
        clean = tag.strip().lower()
        if total_len + len(clean) + 1 <= 480:
            final_tags.append(clean)
            total_len += len(clean) + 1

    return final_tags


def build_seo_description(
    title: str,
    category: str,
    debate_question: str,
    affiliate_links: list[dict[str, str]],
    credit_attribution: str = "",
) -> str:
    """Build a search-indexed, high-engagement description."""
    cat = str(category).upper()
    tags = generate_seo_tags(cat)
    hashtags = " ".join([f"#{t.replace(' ', '')}" for t in tags[:7]])

    lines = [
        title,
        "",
        f"💬 QUESTION OF THE DAY: {debate_question}",
        "Drop your answer in the comments below! 👇",
        "",
        "🛒 FEATURED GEAR & EXCLUSIVE OFFERS:",
    ]

    for item in affiliate_links:
        lines.append(f"• {item.get('cta', 'Check out')}: {item.get('url', '')}")

    lines.extend([
        "",
        "💼 BRAND PARTNERSHIPS & SPONSORSHIPS:",
        "Contact: partnerships@vyralx.media",
        "",
        "---",
        "⚖️ Copyright & Fair Use Notice:",
        credit_attribution or "This video is curated and remixed for commentary, review, and educational value under Fair Use principles.",
        "For inquiries or credit adjustments, contact: copyright@vyralx.media",
        "",
        hashtags,
    ])

    return "\n".join(lines)
