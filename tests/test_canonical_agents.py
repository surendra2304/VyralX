"""Tests for Stratex, Cortex, Futuris, and Forge FRIDAY Universe integrations."""
from unittest.mock import patch

import pytest

from app.services.cortex import extract_semantic_entities, verify_script_coherence
from app.services.forge import synthesize_visual_badge, validate_filter_graph
from app.services.futuris import predict_publish_window, simulate_retention_curve
from app.services.stratex import evaluate_topic_strategy, score_content_pillars


def test_stratex_evaluation_heuristic():
    with pytest.raises(ValueError, match="cannot be empty"):
        evaluate_topic_strategy("")

    with patch("app.services.stratex.configured_peers", return_value={}):
        res = evaluate_topic_strategy("AI Breakthrough In Autonomous Energy", audience="tech enthusiasts")
        assert res["status"] == "heuristic_fallback"
        assert res["strategic_score"] >= 0.70
        assert "technology_and_education" in res["pillar_alignment"]
        assert res["target_demographic"] == "tech enthusiasts"
        assert len(res["recommendations"]) > 0


def test_stratex_evaluation_peer():
    with patch("app.services.stratex.configured_peers", return_value={"stratex": True}):
        with patch("app.services.stratex.post_peer_json", return_value={"strategic_score": 0.94, "pillar_alignment": "frontier_ai"}):
            res = evaluate_topic_strategy("Quantum Computing")
            assert res["status"] == "evaluated_by_peer"
            assert res["strategic_score"] == 0.94
            assert res["pillar_alignment"] == "frontier_ai"


def test_stratex_pillar_scoring():
    topic = "Renewable Solar Energy and Battery Breakthroughs"
    pillars = ["clean tech", "culinary recipes", "crypto trading"]
    scores = score_content_pillars(topic, pillars)
    assert scores["clean tech"] > scores["culinary recipes"]
    assert score_content_pillars(topic, []) == {"general": 1.0}


def test_cortex_entity_extraction_heuristic():
    assert extract_semantic_entities("") == {"entities": [], "concepts": [], "status": "empty"}

    with patch("app.services.cortex.configured_peers", return_value={}):
        script = "Nikola Tesla invented the alternating current generator producing 500 megawatts in New York."
        res = extract_semantic_entities(script)
        assert res["status"] == "heuristic_fallback"
        assert any("Nikola Tesla" in e or "Tesla" in e or "New York" in e for e in res["entities"])
        assert len(res["concepts"]) > 0
        assert any("500 megawatts" in m for m in res["metrics_found"])


def test_cortex_entity_extraction_peer():
    with patch("app.services.cortex.configured_peers", return_value={"cortex": True}):
        with patch("app.services.cortex.post_peer_json", return_value={"entities": ["AI", "FRIDAY"], "concepts": ["agent"]}):
            res = extract_semantic_entities("Autonomous systems")
            assert res["status"] == "extracted_by_peer"
            assert "FRIDAY" in res["entities"]


def test_cortex_script_coherence():
    assert verify_script_coherence("")["coherence_score"] == 0.0

    script = "Have you seen this crazy breakthrough? It completely flips standard engineering on its head. Subscribe for part two!"
    res = verify_script_coherence(script)
    assert res["has_hook"] is True
    assert res["has_cta"] is True
    assert res["coherence_score"] >= 0.80
    assert res["sentences_count"] == 3


def test_futuris_retention_simulation_heuristic():
    with pytest.raises(ValueError, match="duration_seconds must be a positive finite number"):
        simulate_retention_curve([], 0)

    segments = [
        {"start_seconds": 0.0, "end_seconds": 2.5, "text": "Hook text"},
        {"start_seconds": 2.5, "end_seconds": 8.0, "text": "Long drag segment"},
    ]
    with patch("app.services.futuris.configured_peers", return_value={}):
        res = simulate_retention_curve(segments, 15.0)
        assert res["status"] == "heuristic_simulation"
        assert len(res["retention_curve"]) > 0
        assert res["average_retention_pct"] > 50.0
        # Segment longer than 4.5s should flag a drop-off risk
        assert len(res["drop_off_risk_points"]) > 0


def test_futuris_retention_simulation_peer():
    with patch("app.services.futuris.configured_peers", return_value={"futuris": True}):
        with patch("app.services.futuris.post_peer_json", return_value={"average_retention_pct": 82.5, "completion_rate_pct": 74.0}):
            res = simulate_retention_curve([], 30.0)
            assert res["status"] == "simulated_by_peer"
            assert res["average_retention_pct"] == 82.5


def test_futuris_publish_window():
    window = predict_publish_window("tech", "creators")
    assert "Tuesday" in window["recommended_days"]
    assert 14 in window["recommended_utc_hours"]


def test_forge_badge_synthesis(tmp_path):
    badge_path = tmp_path / "badge.svg"
    res = synthesize_visual_badge("VIRAL BREAKTHROUGH", badge_path, theme="neon")
    assert res == badge_path
    content = badge_path.read_text(encoding="utf-8")
    assert "<svg" in content
    assert "VIRAL BREAKTHROUGH" in content

    # Test gold theme
    gold_path = tmp_path / "badge_gold.svg"
    synthesize_visual_badge("GOLD MEDAL", gold_path, theme="gold")
    assert "#f59e0b" in gold_path.read_text(encoding="utf-8")


def test_forge_filter_validation():
    assert validate_filter_graph([])["valid"] is False
    assert validate_filter_graph(["scale=1080:1920", "null"])["valid"] is True
    assert validate_filter_graph(["scale=1080:1920; malicious_cmd"])["valid"] is False
