"""Client integration for Cortex, the cognition, knowledge graph, and reasoning specialist of the FRIDAY Universe."""
from __future__ import annotations

import logging
import re
from typing import Any

from app.services.peers import configured_peers, post_peer_json

log = logging.getLogger("vyralx.cortex")


def extract_semantic_entities(script: str) -> dict[str, Any]:
    """Extract semantic entities, factual concepts, and key topics from narration."""
    clean_text = str(script).strip()
    if not clean_text:
        return {"entities": [], "concepts": [], "status": "empty"}

    if "cortex" in configured_peers():
        try:
            payload = {
                "source_agent": "vyralx",
                "action": "cognition.extract_entities",
                "text": clean_text[:4000],
            }
            response = post_peer_json("cortex", "/v1/cognition/entities", payload, timeout_seconds=6.0)
            log.info("Cortex entity extraction received for text length=%s", len(clean_text))
            return {
                "status": "extracted_by_peer",
                "entities": list(response.get("entities", [])),
                "concepts": list(response.get("concepts", [])),
                "details": response,
            }
        except Exception as exc:
            log.warning("Cortex peer call failed; using local NLP entity extractor: %s", exc)

    # Local deterministic entity and concept extraction
    capitalized = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", clean_text)
    numbers_with_units = re.findall(
        r"\b\d+(?:[.,]\d+)?(?:\s*(?:megawatts|kilowatts|gigawatts|watts|seconds|minutes|hours|days|years|percent|%|million|billion|trillion|mph|km/h|gw|mw|kw|kg|lbs|dollars|\$))?\b",
        clean_text,
        re.IGNORECASE,
    )
    
    stop_words = {"The", "This", "That", "When", "What", "How", "Why", "Where", "In", "On", "At", "To", "And", "Or", "If"}
    filtered_entities = sorted({e for e in capitalized if e not in stop_words})
    
    words = [w.lower() for w in re.findall(r"\b[a-z]{4,}\b", clean_text)]
    from collections import Counter
    counts = Counter(words)
    top_concepts = [w for w, _ in counts.most_common(8)]

    return {
        "status": "heuristic_fallback",
        "entities": filtered_entities[:10],
        "concepts": top_concepts,
        "metrics_found": numbers_with_units[:8],
        "details": {"total_words": len(clean_text.split())},
    }


def verify_script_coherence(script: str) -> dict[str, Any]:
    """Verify narrative coherence, sentence rhythm, and hook/CTA presence."""
    clean_text = str(script).strip()
    if not clean_text:
        return {"coherence_score": 0.0, "has_hook": False, "has_cta": False, "flags": ["empty_script"]}

    sentences = [s.strip() for s in re.split(r"[.!?]+", clean_text) if s.strip()]
    if not sentences:
        return {"coherence_score": 0.0, "has_hook": False, "has_cta": False, "flags": ["no_complete_sentences"]}

    # Hook verification (first sentence should be engaging, < 20 words)
    first_sentence = sentences[0]
    first_words = first_sentence.split()
    hook_score = 1.0 if len(first_words) <= 18 else 0.7

    # CTA verification (last sentence often contains subscribe/follow/comment/watch)
    last_sentence = sentences[-1].lower()
    cta_words = {"subscribe", "follow", "comment", "share", "watch", "next", "find out", "tell us"}
    has_cta = any(w in last_sentence for w in cta_words)

    # Rhythm check: variance in sentence length keeps viewers engaged
    lengths = [len(s.split()) for s in sentences]
    avg_len = sum(lengths) / len(lengths)
    has_variance = max(lengths) - min(lengths) >= 4 if len(lengths) > 1 else False

    flags = []
    if len(first_words) > 22:
        flags.append("Opening sentence is too long for a short-form viral hook.")
    if not has_cta:
        flags.append("Script does not conclude with an explicit viewer call to action.")
    if avg_len > 25:
        flags.append("Average sentence length is high; short-form scripts benefit from punchier delivery.")

    coherence = 0.50 + (0.20 if hook_score > 0.8 else 0.10) + (0.15 if has_cta else 0.05) + (0.15 if has_variance else 0.05)

    return {
        "coherence_score": round(min(1.0, coherence), 2),
        "sentences_count": len(sentences),
        "average_sentence_words": round(avg_len, 1),
        "has_hook": hook_score > 0.8,
        "has_cta": has_cta,
        "has_rhythm_variance": has_variance,
        "flags": flags,
    }
