"""Viral hook generation engine designed for maximum retention on short-form video."""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("vyralx.hooks")

# High-conversion emotional triggers and curiosity catalysts
POWER_WORDS = {
    "secret", "insane", "never", "truth", "exposed", "stop", "mistake", "warning",
    "hidden", "shocking", "ultimate", "nobody", "banned", "illegal", "changed",
    "genius", "destroy", "crazy", "unbelievable", "instantly", "formula",
}


def score_hook_virality(hook_text: str) -> dict[str, Any]:
    """Score hook virality based on word economy, power words, and curiosity gap."""
    text = " ".join(str(hook_text).strip().split())
    if not text:
        return {"score": 0.0, "word_count": 0, "power_words_count": 0, "grade": "F"}

    words = re.findall(r"\w+", text.lower())
    count = len(words)

    # Word economy: 6 to 14 words is ideal for vertical video hooks (< 3.2s speech)
    if 6 <= count <= 14:
        economy_score = 1.0
    elif count < 6:
        economy_score = 0.75
    elif count <= 18:
        economy_score = 0.70
    else:
        economy_score = max(0.3, 1.0 - (count - 14) * 0.05)

    power_matches = [w for w in words if w in POWER_WORDS]
    power_score = min(1.0, len(power_matches) * 0.35 + 0.30 if power_matches else 0.30)

    # Question mark or contrast creates curiosity gap
    has_curiosity = "?" in text or any(w in words for w in ("why", "how", "what", "this", "here"))
    curiosity_score = 1.0 if has_curiosity else 0.65

    final_score = round(0.40 * economy_score + 0.35 * power_score + 0.25 * curiosity_score, 2)
    grade = "S" if final_score >= 0.88 else "A" if final_score >= 0.75 else "B" if final_score >= 0.60 else "C"

    return {
        "score": final_score,
        "grade": grade,
        "word_count": count,
        "power_words_count": len(power_matches),
        "power_words": power_matches,
        "optimal_economy": 6 <= count <= 14,
    }


def generate_viral_hooks(topic: str, *, audience: str = "general") -> list[dict[str, Any]]:
    """Generate 5 distinct psychological hook archetypes for any video topic."""
    clean_topic = str(topic).strip()
    if not clean_topic:
        raise ValueError("Topic cannot be empty for viral hook generation")

    topic_clean = re.sub(r"^[Hh]ow to\s+", "", clean_topic, flags=re.IGNORECASE).rstrip(".!?")

    archetypes = [
        {
            "archetype": "Negative Warning",
            "psychology": "Fear of missing out or making a critical mistake",
            "hook_text": f"Stop doing this with {topic_clean} before it is too late!",
            "on_screen_caption": f"STOP DOING THIS WITH {topic_clean.upper()}!",
        },
        {
            "archetype": "Contrarian Truth",
            "psychology": "Challenging conventional wisdom with high contrast",
            "hook_text": f"Everything you have been told about {topic_clean} is completely wrong.",
            "on_screen_caption": f"THE TRUTH ABOUT {topic_clean.upper()}",
        },
        {
            "archetype": "Curiosity Gap",
            "psychology": "Creating an immediate informational vacuum",
            "hook_text": f"Here is the hidden secret behind {topic_clean} nobody talks about.",
            "on_screen_caption": f"THE SECRET BEHIND {topic_clean.upper()}",
        },
        {
            "archetype": "High Stakes Question",
            "psychology": "Direct audience address with a compelling riddle",
            "hook_text": f"Did you know this crazy fact about {topic_clean}?",
            "on_screen_caption": f"DID YOU KNOW THIS ABOUT {topic_clean.upper()}?",
        },
        {
            "archetype": "Rapid Breakthrough",
            "psychology": "Promise of immediate insider transformation",
            "hook_text": f"This insane breakthrough in {topic_clean} changes everything.",
            "on_screen_caption": f"INSANE BREAKTHROUGH IN {topic_clean.upper()}",
        },
    ]

    scored_hooks = []
    for item in archetypes:
        metrics = score_hook_virality(item["hook_text"])
        scored_hooks.append({
            **item,
            "virality_metrics": metrics,
            "overall_score": metrics["score"],
        })

    scored_hooks.sort(key=lambda x: x["overall_score"], reverse=True)
    return scored_hooks


def select_optimal_hook(hooks: list[dict[str, Any]]) -> dict[str, Any]:
    """Select the highest-performing hook from candidates."""
    if not hooks:
        raise ValueError("Cannot select from an empty hooks list")
    return sorted(hooks, key=lambda x: x.get("overall_score", 0), reverse=True)[0]
