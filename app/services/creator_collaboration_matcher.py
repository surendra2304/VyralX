"""
VyralX/app/services/creator_collaboration_matcher.py — VyralX Creator Collaboration Matcher.

Creator collaboration matching, audience overlap analysis, collaboration recommendation,
and partnership success prediction.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class CreatorProfile:
    """A creator's profile for matching."""
    creator_id: str
    niche: str = ""
    audience_size: int = 0
    engagement_rate: float = 0.0
    content_style: str = ""
    collaboration_history: int = 0


@dataclass
class CollaborationMatch:
    """A collaboration match between creators."""
    match_id: str
    creator_a: str
    creator_b: str
    compatibility_score: float = 0.0
    audience_overlap: float = 0.0
    content_synergy: float = 0.0
    predicted_reach: int = 0
    reasons: list[str] = field(default_factory=list)


@dataclass
class CollaborationOutcome:
    """Outcome of a collaboration."""
    outcome_id: str
    collaboration_id: str
    creators: list[str] = field(default_factory=list)
    combined_views: int = 0
    growth_rate: float = 0.0
    satisfaction: float = 0.5
    created_at: float = field(default_factory=time.time)


class CreatorCollaborationMatcher:
    """Engine for creator collaboration matching."""

    def __init__(self) -> None:
        self._profiles: dict[str, CreatorProfile] = {}
        self._matches: list[CollaborationMatch] = []
        self._outcomes: list[CollaborationOutcome] = []

    def register_creator(self, creator_id: str, niche: str, audience_size: int,
                         engagement_rate: float = 0.0, content_style: str = "",
                         collaboration_history: int = 0) -> CreatorProfile:
        """Register a creator."""
        profile = CreatorProfile(
            creator_id=creator_id, niche=niche, audience_size=audience_size,
            engagement_rate=engagement_rate, content_style=content_style,
            collaboration_history=collaboration_history,
        )
        self._profiles[creator_id] = profile
        return profile

    def find_match(self, creator_a: str, creator_b: str) -> CollaborationMatch:
        """Find collaboration match between two creators."""
        a = self._profiles.get(creator_a)
        b = self._profiles.get(creator_b)
        if not a or not b:
            raise HTTPException(status_code=404, detail="Creator not found")

        match_id = f"match_{uuid.uuid4().hex[:12]}"
        match = CollaborationMatch(
            match_id=match_id, creator_a=creator_a, creator_b=creator_b,
        )

        # Audience overlap (simplified)
        overlap = 0.0
        if a.niche and b.niche:
            if a.niche == b.niche:
                overlap = 0.8
            elif a.niche in b.niche or b.niche in a.niche:
                overlap = 0.5
            else:
                overlap = 0.2

        # Content synergy
        compatibility = 0.0
        if a.content_style and b.content_style:
            compatibility = 0.6 if a.content_style != b.content_style else 0.4
        else:
            compatibility = 0.5

        match.audience_overlap = overlap
        match.content_synergy = compatibility
        match.compatibility_score = (overlap * 0.4 + compatibility * 0.3 +
                                     (a.engagement_rate + b.engagement_rate) * 0.3)

        match.predicted_reach = int((a.audience_size + b.audience_size) * 1.2 * match.compatibility_score)

        match.reasons = [
            f"Niche overlap: {overlap:.0%}",
            f"Content synergy: {compatibility:.0%}",
            f"Predicted reach: {match.predicted_reach}",
        ]

        self._matches.append(match)
        return match

    def record_outcome(self, collaboration_id: str, creators: list[str],
                       combined_views: int, growth_rate: float = 0.0,
                       satisfaction: float = 0.5) -> CollaborationOutcome:
        """Record collaboration outcome."""
        outcome_id = f"out_{uuid.uuid4().hex[:12]}"
        outcome = CollaborationOutcome(
            outcome_id=outcome_id, collaboration_id=collaboration_id,
            creators=creators, combined_views=combined_views,
            growth_rate=growth_rate, satisfaction=satisfaction,
        )
        self._outcomes.append(outcome)
        return outcome

    def get_matches(self, min_score: float = 0.0) -> list[dict[str, Any]]:
        """Get collaboration matches."""
        matches = [m for m in self._matches if m.compatibility_score >= min_score]
        return [
            {"creator_a": m.creator_a, "creator_b": m.creator_b,
             "score": round(m.compatibility_score, 2),
             "overlap": m.audience_overlap, "synergy": m.content_synergy}
            for m in matches
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_creators": len(self._profiles),
            "total_matches": len(self._matches),
            "total_outcomes": len(self._outcomes),
            "avg_compatibility": round(
                sum(m.compatibility_score for m in self._matches) / max(1, len(self._matches)), 2
            ) if self._matches else 0,
            "engine_status": "operational",
        }


engine = CreatorCollaborationMatcher()


@router.post("/vyralx/collab/creators")
async def register_creator(creator_id: str, niche: str, audience_size: int,
                           engagement_rate: float = 0.0, content_style: str = "",
                           collaboration_history: int = 0):
    """Register a creator."""
    profile = engine.register_creator(creator_id, niche, audience_size,
                                      engagement_rate, content_style, collaboration_history)
    return {"creator_id": creator_id, "niche": niche, "audience_size": audience_size}


@router.post("/vyralx/collab/match")
async def find_match(creator_a: str, creator_b: str):
    """Find collaboration match."""
    match = engine.find_match(creator_a, creator_b)
    return {
        "creator_a": creator_a,
        "creator_b": creator_b,
        "compatibility": match.compatibility_score,
        "predicted_reach": match.predicted_reach,
        "reasons": match.reasons,
    }


@router.post("/vyralx/collab/outcomes")
async def record_outcome(collaboration_id: str, creators: list[str],
                         combined_views: int, growth_rate: float = 0.0,
                         satisfaction: float = 0.5):
    """Record collaboration outcome."""
    outcome = engine.record_outcome(collaboration_id, creators, combined_views,
                                    growth_rate, satisfaction)
    return {"outcome_id": outcome.outcome_id, "combined_views": combined_views}


@router.get("/vyralx/collab/matches")
async def get_matches(min_score: float = 0.0):
    """Get collaboration matches."""
    return {"matches": engine.get_matches(min_score)}


@router.get("/vyralx/collab/report")
async def collab_report():
    """Get collaboration matcher report."""
    return engine.get_report()
