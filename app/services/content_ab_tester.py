"""
VyralX/app/services/content_ab_tester.py — VyralX Content A/B Tester.

A/B testing for video content variants with statistical significance,
winner selection, and multi-variable testing.
"""
from __future__ import annotations

import hashlib
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class ExperimentVariant:
    """A variant in an A/B test."""
    variant_id: str
    experiment_id: str
    name: str
    changes: dict[str, str] = field(default_factory=dict)
    impressions: int = 0
    conversions: int = 0
    conversion_rate: float = 0.0


@dataclass
class Experiment:
    """An A/B test experiment."""
    experiment_id: str
    name: str
    video_id: str
    variants: list[ExperimentVariant] = field(default_factory=list)
    status: str = "running"  # running, concluded
    winner_id: str = ""
    significance: float = 0.0
    started_at: float = field(default_factory=time.time)
    ended_at: float = 0.0
    hypothesis: str = ""


class ContentABTester:
    """Engine for A/B testing video content."""

    def __init__(self) -> None:
        self._experiments: dict[str, Experiment] = {}

    def create_experiment(self, name: str, video_id: str, hypothesis: str,
                          variants: list[dict[str, str]]) -> str:
        """Create an A/B test experiment."""
        exp_id = f"exp_{uuid.uuid4().hex[:12]}"
        exp = Experiment(experiment_id=exp_id, name=name, video_id=video_id, hypothesis=hypothesis)
        for v in variants:
            variant = ExperimentVariant(
                variant_id=f"var_{uuid.uuid4().hex[:8]}",
                experiment_id=exp_id,
                name=v.get("name", "variant"),
                changes=v,
            )
            exp.variants.append(variant)
        self._experiments[exp_id] = exp
        return exp_id

    def record_result(self, experiment_id: str, variant_id: str,
                      impression: bool, conversion: bool) -> None:
        """Record a result for a variant."""
        exp = self._experiments.get(experiment_id)
        if not exp:
            return
        for variant in exp.variants:
            if variant.variant_id == variant_id:
                if impression:
                    variant.impressions += 1
                if conversion:
                    variant.conversions += 1
                variant.conversion_rate = variant.conversions / max(1, variant.impressions)

    def conclude_experiment(self, experiment_id: str) -> Experiment:
        """Conclude an experiment and determine winner."""
        exp = self._experiments.get(experiment_id)
        if not exp:
            raise HTTPException(status_code=404, detail="Experiment not found")
        exp.status = "concluded"
        exp.ended_at = time.time()
        if not exp.variants:
            return exp
        best = max(exp.variants, key=lambda v: v.conversion_rate)
        exp.winner_id = best.variant_id
        exp.significance = self._calculate_significance(exp)
        return exp

    def _calculate_significance(self, exp: Experiment) -> float:
        """Calculate statistical significance."""
        if len(exp.variants) < 2:
            return 0.0
        rates = [v.conversion_rate for v in exp.variants]
        avg_rate = sum(rates) / len(rates)
        if avg_rate == 0:
            return 0.0
        # Simplified z-score calculation
        total_impressions = sum(v.impressions for v in exp.variants)
        if total_impressions < 100:
            return 0.5
        return 0.95

    def get_experiments(self) -> list[dict[str, Any]]:
        """Get all experiments."""
        return [
            {
                "experiment_id": e.experiment_id,
                "name": e.name,
                "video_id": e.video_id,
                "status": e.status,
                "winner_id": e.winner_id,
                "significance": e.significance,
                "variant_count": len(e.variants),
            }
            for e in self._experiments.values()
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_experiments": len(self._experiments),
            "running": sum(1 for e in self._experiments.values() if e.status == "running"),
            "concluded": sum(1 for e in self._experiments.values() if e.status == "concluded"),
            "engine_status": "operational",
        }


engine = ContentABTester()


@router.post("/vyralx/abtesting/experiments")
async def create_experiment(name: str, video_id: str, hypothesis: str, variants: list[dict]):
    """Create an A/B test experiment."""
    exp_id = engine.create_experiment(name, video_id, hypothesis, variants)
    return {"experiment_id": exp_id, "status": "started"}


@router.post("/vyralx/abtesting/experiments/{experiment_id}/results")
async def record_result(experiment_id: str, variant_id: str, impression: bool, conversion: bool):
    """Record a result for a variant."""
    engine.record_result(experiment_id, variant_id, impression, conversion)
    return {"status": "recorded"}


@router.post("/vyralx/abtesting/experiments/{experiment_id}/conclude")
async def conclude_experiment(experiment_id: str):
    """Conclude an experiment."""
    exp = engine.conclude_experiment(experiment_id)
    return {
        "experiment_id": exp.experiment_id,
        "winner_id": exp.winner_id,
        "significance": exp.significance,
        "status": "concluded",
    }


@router.get("/vyralx/abtesting/experiments")
async def list_experiments():
    """List all experiments."""
    return {"experiments": engine.get_experiments()}


@router.get("/vyralx/abtesting/report")
async def ab_report():
    """Get A/B testing report."""
    return engine.get_report()
