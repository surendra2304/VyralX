"""Tests for VyralX Audience & Reach Reinforcement Learning Engine."""
import json
import pytest
from pathlib import Path
from app.services.audience_reach_learner import (
    AudienceReachLearner,
    calculate_optimal_post_time,
    find_cohort_for_topic,
    AUDIENCE_COHORTS
)


def test_find_cohort_for_topic():
    cohort_id, info = find_cohort_for_topic("extreme wealth and cash")
    assert cohort_id == "finance_and_wealth"
    assert "Finance" in info["name"]

    cohort_id, info = find_cohort_for_topic("satisfying molten metal")
    assert cohort_id == "satisfying_precision"

    cohort_id, info = find_cohort_for_topic("police interrogation drama")
    assert cohort_id == "psychology_and_tension"


def test_calculate_optimal_post_time():
    res = calculate_optimal_post_time("day trading profit surge")
    assert res["cohort_id"] == "finance_and_wealth"
    assert "optimal_post_time_utc" in res
    assert "optimal_post_time_ist" in res
    assert "optimal_post_time_est" in res
    assert "IST" in res["optimal_post_time_ist"]
    assert len(res["optimal_post_time_utc"]) == 20  # ISO format YYYY-MM-DDTHH:MM:SSZ


def test_audience_reach_learner_weights(tmp_path: Path):
    state_file = tmp_path / "learning_state.json"
    learner = AudienceReachLearner(state_file=state_file)

    catalog = [
        {"id": "1", "title": "Trading Crash", "topic": "stock market crash and trading"},
        {"id": "2", "title": "Laser Cutting", "topic": "satisfying precision cnc"},
    ]

    # Candidate selection on fresh state
    cand, weight = learner.select_weighted_candidate(catalog, set())
    assert cand is not None
    assert weight >= 1.0

    # Simulate processed candidate
    cand_filtered, _ = learner.select_weighted_candidate(catalog, {"mixkit_1"})
    assert cand_filtered is not None
    assert cand_filtered["id"] == "2"

    # Test draft record
    learner.record_draft_created("test_vid_123", "stock market crash and trading", {"target": "mock"})
    assert learner.state["total_drafts_created"] == 1
    assert len(learner.state["history"]) == 1

    # Reload from disk
    reloaded = AudienceReachLearner(state_file=state_file)
    assert reloaded.state["total_drafts_created"] == 1
