"""
VyralX/app/services/content_moderation_engine.py — VyralX Content Moderation Engine.

Automated content moderation, policy enforcement, toxicity detection,
and community guidelines management.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class ContentItem:
    """A content item to moderate."""
    content_id: str
    text: str = ""
    media_type: str = "text"  # text, image, video, audio
    metadata: dict = field(default_factory=dict)
    submitted_by: str = ""


@dataclass
class ModerationResult:
    """Result of content moderation."""
    result_id: str
    content_id: str
    decision: str = "pending"  # approved, rejected, flagged, pending
    scores: dict[str, float] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    policy_violations: list[str] = field(default_factory=list)
    reviewed_at: float = field(default_factory=time.time)


@dataclass
class ModerationPolicy:
    """A moderation policy."""
    policy_id: str
    name: str
    rules: list[dict] = field(default_factory=list)
    thresholds: dict[str, float] = field(default_factory=dict)
    description: str = ""


class ContentModerationEngine:
    """Engine for automated content moderation."""

    def __init__(self) -> None:
        self._results: list[ModerationResult] = []
        self._policies: dict[str, ModerationPolicy] = {}

    def create_policy(self, name: str, description: str = "",
                      thresholds: dict[str, float] | None = None) -> ModerationPolicy:
        """Create a moderation policy."""
        policy_id = f"pol_{uuid.uuid4().hex[:12]}"
        policy = ModerationPolicy(
            policy_id=policy_id, name=name, description=description,
            thresholds=thresholds or {"toxicity": 0.7, "spam": 0.8, "harassment": 0.6},
        )
        policy.rules = [
            {"type": "toxicity", "action": "flag", "threshold": policy.thresholds["toxicity"]},
            {"type": "spam", "action": "reject", "threshold": policy.thresholds["spam"]},
            {"type": "harassment", "action": "reject", "threshold": policy.thresholds["harassment"]},
        ]
        self._policies[policy_id] = policy
        return policy

    def moderate(self, content: ContentItem, policy_id: str = "") -> ModerationResult:
        """Moderate a content item."""
        result_id = f"mod_{uuid.uuid4().hex[:12]}"
        result = ModerationResult(result_id=result_id, content_id=content.content_id)

        # Analyze text content
        text = content.text.lower()
        words = text.split()

        # Toxicity score (based on keywords)
        toxic_words = ["hate", "kill", "attack", "harm", "abuse", "violent"]
        toxic_count = sum(1 for w in words if any(t in w for t in toxic_words))
        result.scores["toxicity"] = min(1.0, toxic_count / max(1, len(words)) * 10)

        # Spam score
        spam_patterns = ["buy now", "click here", "free money", "limited offer", "www."]
        spam_count = sum(1 for p in spam_patterns if p in text)
        result.scores["spam"] = min(1.0, spam_count * 0.3)

        # Harassment score
        harass_patterns = ["you are", "you're", "stupid", "idiot", "worthless"]
        harass_count = sum(1 for p in harass_patterns if p in text)
        result.scores["harassment"] = min(1.0, harass_count * 0.4)

        # Apply policy thresholds
        policy = self._policies.get(policy_id)
        thresholds = policy.thresholds if policy else {"toxicity": 0.7, "spam": 0.8, "harassment": 0.6}

        for score_name, score_value in result.scores.items():
            threshold = thresholds.get(score_name, 0.7)
            if score_value > threshold:
                result.policy_violations.append(score_name)
                result.flags.append(f"{score_name} exceeded threshold ({score_value:.2f} > {threshold})")
                if score_name == "spam":
                    result.decision = "rejected"
                elif result.decision != "rejected":
                    result.decision = "flagged"

        if not result.policy_violations:
            result.decision = "approved"

        self._results.append(result)
        return result

    def get_results(self, decision: str | None = None) -> list[dict[str, Any]]:
        """Get moderation results."""
        results = self._results
        if decision:
            results = [r for r in results if r.decision == decision]
        return [
            {"content_id": r.content_id, "decision": r.decision,
             "violations": r.policy_violations, "flags": r.flags[:2]}
            for r in results[-10:]
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_results": len(self._results),
            "total_policies": len(self._policies),
            "approved": sum(1 for r in self._results if r.decision == "approved"),
            "flagged": sum(1 for r in self._results if r.decision == "flagged"),
            "rejected": sum(1 for r in self._results if r.decision == "rejected"),
            "engine_status": "operational",
        }


engine = ContentModerationEngine()


@router.post("/vyralx/moderation/policies")
async def create_policy(name: str, description: str = "", thresholds: dict[str, float] | None = None):
    """Create a moderation policy."""
    policy = engine.create_policy(name, description, thresholds)
    return {"policy_id": policy.policy_id, "name": policy.name}


@router.post("/vyralx/moderation/moderate")
async def moderate(content_id: str, text: str = "", media_type: str = "text",
                   submitted_by: str = "", policy_id: str = ""):
    """Moderate a content item."""
    content = ContentItem(content_id=content_id, text=text, media_type=media_type, submitted_by=submitted_by)
    result = engine.moderate(content, policy_id)
    return {
        "content_id": content_id,
        "decision": result.decision,
        "violations": result.policy_violations,
        "scores": {k: round(v, 2) for k, v in result.scores.items()},
    }


@router.get("/vyralx/moderation/results")
async def get_results(decision: str | None = None):
    """Get moderation results."""
    return {"results": engine.get_results(decision)}


@router.get("/vyralx/moderation/report")
async def moderation_report():
    """Get moderation engine report."""
    return engine.get_report()
