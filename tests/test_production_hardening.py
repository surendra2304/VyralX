"""Regression tests for production workflow hardening."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import Source
from app.services.captions import segment_script, write_srt
from app.services.content import _extract_json, generate_content_pack
from app.services.intelx import normalize_intelx_reports
from app.services.rights import append_stock_attribution, source_is_publishable


def test_long_script_captioning_preserves_all_words():
    script = " ".join(f"word{index}" for index in range(600))
    cues = segment_script(script, 15, max_chars=30)
    assert " ".join(cue["text"] for cue in cues) == script
    assert len(cues) <= 30
    assert cues[0]["start_seconds"] == 0
    assert cues[-1]["end_seconds"] == 15


def test_srt_rejects_overlapping_and_nonfinite_cues(tmp_path: Path):
    with pytest.raises(ValueError, match="must not overlap"):
        write_srt([
            {"start_seconds": 0, "end_seconds": 2, "text": "first"},
            {"start_seconds": 1, "end_seconds": 3, "text": "second"},
        ], tmp_path / "overlap.srt")
    with pytest.raises(ValueError, match="finite positive time range"):
        write_srt([
            {"start_seconds": float("nan"), "end_seconds": 2, "text": "invalid"},
        ], tmp_path / "nan.srt")


def test_rights_gate_rejects_placeholder_and_untrusted_pexels_evidence():
    assert not source_is_publishable(Source(
        title="Placeholder", rights_verified=True, license_name="unknown", permission_reference="TBD",
    ))
    assert not source_is_publishable(Source(
        title="Forged stock", platform="pexels", source_url="https://example.invalid/video/123/",
        rights_verified=True, license_name="Pexels Content License",
        permission_reference="https://www.pexels.com/license/",
    ))
    assert source_is_publishable(Source(
        title="Official stock", platform="pexels", source_url="https://www.pexels.com/video/123/",
        rights_verified=True, license_name="Pexels Content License",
        permission_reference="https://www.pexels.com/license/",
    ))


def test_stock_credits_fail_closed_when_full_urls_do_not_fit():
    source = SimpleNamespace(
        platform="pexels",
        source_url="https://www.pexels.com/video/" + ("x" * 2600),
        creator="Creator",
        permission_reference="https://www.pexels.com/license/" + ("y" * 2600),
    )
    with pytest.raises(ValueError, match="attribution exceeds"):
        append_stock_attribution("Short intro", [(SimpleNamespace(id=1), source)])


def test_intelx_normalization_requires_traceability_and_filters_irrelevant_reports():
    reports = normalize_intelx_reports({
        "items": [
            {
                "id": "solar-1", "title": "Solar panel efficiency",
                "summary": "Solar output depends on irradiance.",
                "key_findings": "Output changes with sunlight.",
                "url": "https://intelx.example/solar/1",
            },
            {
                "id": "sports-2", "title": "Basketball finals",
                "summary": "The team won the championship.",
            },
            {"title": "Untraceable report", "summary": "Solar panels convert sunlight."},
        ]
    }, "How solar panels work")
    assert len(reports) == 1
    assert reports[0]["report_id"] == "solar-1"
    assert reports[0]["source_url"] == "https://intelx.example/solar/1"
    assert reports[0]["key_findings"] == ["Output changes with sunlight."]


def test_intelx_normalization_accepts_live_sector_report_shape():
    reports = normalize_intelx_reports([
        {
            "report_id": "ix-solar-01",
            "asset_or_sector": "Solar power",
            "published_at": "2026-10-10T00:00:00Z",
            "summary": "Solar panel efficiency increases with direct irradiance.",
            "key_findings": ["Solar panel output varies with sunlight."],
            "tags": ["renewable energy"],
            "sentiment_score": 0.2,
        }
    ], "solar power generation")
    assert len(reports) == 1
    assert reports[0]["report_id"] == "ix-solar-01"
    assert reports[0]["title"] == "Solar power"
    assert reports[0]["published_at"] == "2026-10-10T00:00:00Z"
    assert reports[0]["key_findings"] == ["Solar panel output varies with sunlight."]


def test_inference_receives_only_topic_matched_intelx_context(monkeypatch):
    from app.services import content as content_service

    monkeypatch.setattr(content_service, "get_settings", lambda: SimpleNamespace(
        inference_url="http://inference:8000",
        inference_api_key="test-key",
        inference_model="",
        inference_generation_path="/v1/task/execute",
        inference_timeout_seconds=3,
    ))
    pack = {
        "hook": "A hook", "script": "A script", "scene_plan": [{"visual": "Solar panels"}],
        "voiceover": "Narration", "caption": "Captions", "title_options": ["A title"],
        "description": "", "tags": [], "thumbnail_brief": "A thumbnail",
    }
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "SUCCESS", "result": {"response": json.dumps(pack)}}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(content_service.httpx, "post", fake_post)
    research_items = [
        {"id": "solar-1", "title": "Solar output", "summary": "Solar output varies by sunlight."},
        {"id": "sports-2", "title": "Basketball finals", "summary": "The team won the championship."},
    ]
    result_pack = generate_content_pack("How solar panels work", research_context=research_items)
    reports = captured["json"]["payload"]["context"]["intelx_research_context"]
    assert [item["report_id"] for item in reports] == ["solar-1"]
    assert reports[0]["title"] == "Solar output"
    assert "solar-1" in result_pack["fact_check_notes"][0]
    assert len(research_items) == 1
    assert research_items[0]["report_id"] == "solar-1"


def test_inference_content_contract_rejects_malformed_scene_plan():
    payload = {
        "hook": "A hook", "script": "A script", "scene_plan": ["not a scene"],
        "voiceover": "Narration", "caption": "Captions", "title_options": ["A title"],
        "description": "", "tags": [], "thumbnail_brief": "A thumbnail",
    }
    with pytest.raises(ValueError, match="usable scene"):
        _extract_json(json.dumps(payload))
