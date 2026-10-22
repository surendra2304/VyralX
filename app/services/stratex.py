"""Client integration for Stratex, the strategy, positioning, and decision analysis specialist of the FRIDAY Universe."""
from __future__ import annotations

import logging
import re
from typing import Any

from app.services.peers import configured_peers, post_peer_json

log = logging.getLogger("vyralx.stratex")


def evaluate_topic_strategy(
    topic: str,
    *,
    audience: str = "general audience",
    tone: str = "clear, energetic and factual",
    pillars: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate strategic positioning and audience affinity for a video project.
    
    If Stratex is configured, queries the peer endpoint; otherwise computes a deterministic
    heuristic strategy assessment based on editorial pillars and audience keywords.
    """
    clean_topic = str(topic).strip()
    if not clean_topic:
        raise ValueError("Topic cannot be empty for strategy evaluation")

    if "stratex" in configured_peers():
        try:
            payload = {
                "source_agent": "vyralx",
                "action": "strategy.evaluate",
                "topic": clean_topic,
                "audience": audience,
                "tone": tone,
                "pillars": pillars or [],
            }
            response = post_peer_json("stratex", "/v1/strategy/evaluate", payload, timeout_seconds=6.0)
            log.info("Stratex strategic evaluation received for topic=%s", clean_topic[:50])
            return {
                "status": "evaluated_by_peer",
                "strategic_score": float(response.get("strategic_score", 0.85)),
                "pillar_alignment": str(response.get("pillar_alignment", "core_pillar")),
                "target_demographic": str(response.get("target_demographic", audience)),
                "recommendations": list(response.get("recommendations", [])),
                "details": response,
            }
        except Exception as exc:
            log.warning("Stratex peer call failed; falling back to local strategy heuristics: %s", exc)

    # Local deterministic strategic heuristics
    words = re.findall(r"\w+", clean_topic.lower())
    high_interest_terms = {
        "ai", "future", "secret", "money", "power", "energy", "truth", "discover",
        "speed", "tech", "science", "million", "ultimate", "revolution", "breakthrough",
        "robotics", "robot", "autonomous", "quantum", "space", "physics", "code",
    }
    overlap = len(set(words).intersection(high_interest_terms))
    score = min(0.95, max(0.60, 0.65 + overlap * 0.08))

    recommendations = []
    if len(words) < 4:
        recommendations.append("Consider sharpening the topic title with high-contrast curiosity phrasing.")
    if overlap == 0:
        recommendations.append("Incorporate stronger power keywords to boost viewer initial click curiosity.")
    recommendations.append(f"Tailor pacing to keep retention high for {audience}.")

    return {
        "status": "heuristic_fallback",
        "strategic_score": round(score, 2),
        "pillar_alignment": "technology_and_education" if any(w in words for w in ("tech", "code", "ai", "science")) else "general_interest",
        "target_demographic": audience,
        "recommendations": recommendations,
        "details": {"evaluated_words_count": len(words), "high_interest_overlap": overlap},
    }


def score_content_pillars(topic: str, pillars: list[str]) -> dict[str, float]:
    """Score topic affinity across configured channel content pillars."""
    if not pillars:
        return {"general": 1.0}

    topic_words = set(re.findall(r"\w+", topic.lower()))
    scores: dict[str, float] = {}

    pillar_expansions = {
        "tech": {"tech", "technology", "software", "ai", "hardware", "battery", "breakthrough", "breakthroughs", "digital"},
        "clean": {"clean", "green", "renewable", "solar", "wind", "climate", "energy", "eco"},
        "crypto": {"crypto", "bitcoin", "blockchain", "ethereum", "token", "web3", "trading"},
        "finance": {"finance", "money", "investing", "trading", "stocks", "wealth", "economy"},
        "science": {"science", "physics", "space", "biology", "research", "quantum"},
        "culinary": {"food", "recipe", "recipes", "cook", "kitchen", "bake", "chef", "culinary"},
    }

    for pillar in pillars:
        clean_pillar = pillar.strip()
        if not clean_pillar:
            continue
        raw_words = set(re.findall(r"\w+", clean_pillar.lower()))
        expanded_words = set(raw_words)
        for w in raw_words:
            if w in pillar_expansions:
                expanded_words.update(pillar_expansions[w])
        common = topic_words.intersection(expanded_words)
        score = len(common) / max(1, len(expanded_words))
        scores[clean_pillar] = round(min(1.0, max(0.1, score + 0.35 if common else 0.1)), 2)

    return scores or {"general": 1.0}
