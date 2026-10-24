"""
VyralX/app/services/content_recommendation_explainer.py — VyralX Content Recommendation Explainer.

Recommendation transparency, explainable AI for content, user trust scoring,
and recommendation fairness auditing.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class RecommendationFactor:
    """A factor in a recommendation."""
    factor_id: str
    name: str
    weight: float = 0.0
    contribution: float = 0.0
    description: str = ""


@dataclass
class ExplainableRecommendation:
    """An explainable recommendation."""
    rec_id: str
    content_id: str
    user_id: str
    factors: list[RecommendationFactor] = field(default_factory=list)
    score: float = 0.0
    explanation: str = ""
    fairness_score: float = 0.5
    created_at: float = field(default_factory=time.time)


@dataclass
class FairnessAudit:
    """A fairness audit of recommendations."""
    audit_id: str
    total_recommendations: int = 0
    demographic_coverage: dict = field(default_factory=dict)
    bias_score: float = 0.0
    recommendations: list[str] = field(default_factory=list)


class ContentRecommendationExplainer:
    """Engine for explainable content recommendations."""

    def __init__(self) -> None:
        self._recommendations: list[ExplainableRecommendation] = []
        self._audits: list[FairnessAudit] = []

    def explain_recommendation(self, content_id: str, user_id: str,
                               factors: list[dict]) -> ExplainableRecommendation:
        """Create an explainable recommendation."""
        rec_id = f"rec_{uuid.uuid4().hex[:12]}"
        rec = ExplainableRecommendation(rec_id=rec_id, content_id=content_id, user_id=user_id)

        for factor in factors:
            rf = RecommendationFactor(
                factor_id=f"f_{uuid.uuid4().hex[:8]}",
                name=factor["name"],
                weight=factor.get("weight", 1.0),
                contribution=factor.get("contribution", 0.0),
                description=factor.get("description", ""),
            )
            rec.factors.append(rf)
            rec.score += rf.contribution * rf.weight

        rec.explanation = (
            f"Recommended based on {len(rec.factors)} factors. "
            f"Top factor: {max(rec.factors, key=lambda f: f.contribution).name}"
        )
        rec.fairness_score = max(0.0, 1.0 - (len(rec.factors) * 0.05))

        self._recommendations.append(rec)
        return rec

    def audit_fairness(self) -> FairnessAudit:
        """Audit recommendation fairness."""
        audit_id = f"fair_{uuid.uuid4().hex[:12]}"
        audit = FairnessAudit(audit_id=audit_id)
        audit.total_recommendations = len(self._recommendations)

        # Check diversity of content across users
        content_ids = [r.content_id for r in self._recommendations]
        unique_content = len(set(content_ids))
        audit.demographic_coverage = {"unique_content": unique_content, "total": len(content_ids)}

        # Calculate bias score (lower is better)
        if len(content_ids) > 0:
            from collections import Counter
            counts = Counter(content_ids)
            max_count = max(counts.values())
            audit.bias_score = max_count / len(content_ids)

        audit.recommendations = [
            "Increase content diversity in recommendations",
            "Add demographic-aware ranking",
            "Monitor for content echo chambers",
        ] if audit.bias_score > 0.5 else [
            "Fairness metrics within acceptable range",
            "Continue monitoring",
        ]

        self._audits.append(audit)
        return audit

    def get_explanations(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """Get explanations."""
        recs = self._recommendations
        if user_id:
            recs = [r for r in recs if r.user_id == user_id]
        return [
            {"content_id": r.content_id, "score": r.score,
             "factor_count": len(r.factors), "fairness": r.fairness_score,
             "explanation": r.explanation[:80]}
            for r in recs[-10:]
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        avg_fairness = (
            sum(r.fairness_score for r in self._recommendations) / max(1, len(self._recommendations))
        ) if self._recommendations else 0
        return {
            "total_recommendations": len(self._recommendations),
            "total_audits": len(self._audits),
            "avg_fairness": round(avg_fairness, 2),
            "engine_status": "operational",
        }


engine = ContentRecommendationExplainer()


@router.post("/vyralx/explainer/recommend")
async def explain_recommendation(content_id: str, user_id: str, factors: list[dict]):
    """Create an explainable recommendation."""
    rec = engine.explain_recommendation(content_id, user_id, factors)
    return {
        "rec_id": rec.rec_id,
        "score": rec.score,
        "factor_count": len(rec.factors),
        "explanation": rec.explanation[:80],
    }


@router.post("/vyralx/explainer/audit")
async def audit_fairness():
    """Audit recommendation fairness."""
    audit = engine.audit_fairness()
    return {
        "audit_id": audit.audit_id,
        "total_recommendations": audit.total_recommendations,
        "bias_score": audit.bias_score,
        "recommendations": audit.recommendations,
    }


@router.get("/vyralx/explainer/explanations")
async def get_explanations(user_id: str | None = None):
    """Get explanations."""
    return {"explanations": engine.get_explanations(user_id)}


@router.get("/vyralx/explainer/report")
async def explainer_report():
    """Get explainer report."""
    return engine.get_report()
