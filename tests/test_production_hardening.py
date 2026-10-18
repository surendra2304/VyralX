"""Regression tests for production workflow hardening."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import Asset, Source
from app.services.captions import segment_script, write_srt
from app.services.content import _extract_json, generate_content_pack
from app.services.intelx import normalize_intelx_reports
from app.services.rights import (
    append_stock_attribution,
    source_is_publishable,
    verified_render_sources,
)


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


def test_stock_attribution_normalizes_platform_whitespace():
    source = SimpleNamespace(
        platform=" Pexels ",
        source_url="https://www.pexels.com/video/123456/",
        creator="Creator",
        permission_reference="https://www.pexels.com/license/",
    )

    description = append_stock_attribution(
        "Original video description", [(SimpleNamespace(id=1), source)]
    )

    assert "Stock footage credits:" in description
    assert "https://www.pexels.com/video/123456/" in description
    assert "https://www.pexels.com/license/" in description


def test_render_rights_gate_supports_all_eight_montage_scenes():
    records = {}
    for asset_id in range(1, 9):
        source_id = 1000 + asset_id
        records[(Asset, asset_id)] = SimpleNamespace(
            id=asset_id, rights_verified=True, source_id=source_id
        )
        records[(Source, source_id)] = SimpleNamespace(
            id=source_id,
            platform="pexels",
            source_url=f"https://www.pexels.com/video/{asset_id}/",
            rights_verified=True,
            license_name="Pexels Content License",
            permission_reference="https://www.pexels.com/license/",
        )

    class FakeSession:
        def get(self, model, key):
            return records.get((model, key))

    render = SimpleNamespace(
        asset_id=1,
        project_id=45,
        options_json=json.dumps({"montage_asset_ids": list(range(1, 9))}),
    )
    verified = verified_render_sources(render, FakeSession())

    assert len(verified) == 8
    assert [asset.id for asset, _ in verified] == list(range(1, 9))


def test_stock_attribution_keeps_creator_credit_when_description_mentions_urls():
    source = SimpleNamespace(
        platform="pexels",
        source_url="https://www.pexels.com/video/123456/",
        creator="Creator\nInjected line",
        permission_reference="https://www.pexels.com/license/",
    )
    original = (
        "Source: https://www.pexels.com/video/123456/\n"
        "License: https://www.pexels.com/license/"
    )

    description = append_stock_attribution("Original description\n" + original, [(SimpleNamespace(id=1), source)])

    assert "Stock footage credits:" in description
    assert "- Creator Injected line (Pexels): https://www.pexels.com/video/123456/" in description
    assert description.count("https://www.pexels.com/video/123456/") == 2


def test_project_render_rights_gate_requires_explicit_complete_scene_list():
    class EmptySession:
        def get(self, model, key):
            return None

    missing_scene_list = SimpleNamespace(asset_id=1, project_id=5, options_json="{}")
    with pytest.raises(ValueError, match="must include montage_asset_ids"):
        verified_render_sources(missing_scene_list, EmptySession())

    one_scene = SimpleNamespace(
        asset_id=1,
        project_id=5,
        options_json=json.dumps({"montage_asset_ids": [1]}),
    )
    with pytest.raises(ValueError, match="between 2 and 8"):
        verified_render_sources(one_scene, EmptySession())

    missing_primary = SimpleNamespace(
        asset_id=1,
        project_id=5,
        options_json=json.dumps({"montage_asset_ids": [2, 3]}),
    )
    with pytest.raises(ValueError, match="include its primary asset"):
        verified_render_sources(missing_primary, EmptySession())


def test_render_rights_gate_rejects_invalid_asset_ids():
    class EmptySession:
        def get(self, model, key):
            return None

    render = SimpleNamespace(
        asset_id=1,
        options_json=json.dumps({"montage_asset_ids": [-1]}),
    )
    with pytest.raises(ValueError, match="invalid asset ID"):
        verified_render_sources(render, EmptySession())


def test_render_rights_gate_rejects_non_object_options():
    class EmptySession:
        def get(self, model, key):
            return None

    render = SimpleNamespace(asset_id=1, options_json="[]")
    with pytest.raises(ValueError, match="JSON object"):
        verified_render_sources(render, EmptySession())


def test_srt_flattens_newlines_inside_caption_text(tmp_path: Path):
    output = write_srt(
        [{"start_seconds": 0, "end_seconds": 2, "text": "<b>First line</b>\n\nSecond line\r\n"}],
        tmp_path / "multiline.srt",
    )
    cue_text = output.read_text(encoding="utf-8").splitlines()[2]
    assert cue_text == "First line Second line"


def test_srt_rejects_cues_that_collapse_to_zero_milliseconds(tmp_path: Path):
    with pytest.raises(ValueError, match="at least 1 millisecond"):
        write_srt(
            [{"start_seconds": 0.0001, "end_seconds": 0.0004, "text": "Too short"}],
            tmp_path / "collapsed.srt",
        )


def test_friday_envelope_rejects_conflicting_inputs_and_payload():
    from app.schemas import UniverseTaskEnvelope

    with pytest.raises(ValueError, match="inputs and payload must match"):
        UniverseTaskEnvelope(
            task_id="friday-contract-conflict",
            task_type="content.generate",
            action="content.generate",
            inputs={"topic": "How solar panels work"},
            payload={"topic": "How basketball works"},
        )


def test_friday_envelope_accepts_legacy_payload_only():
    from app.schemas import UniverseTaskEnvelope

    envelope = UniverseTaskEnvelope(
        task_id="friday-contract-payload-only",
        action="content.generate",
        payload={"topic": "How solar panels work"},
    )

    assert envelope.inputs == envelope.payload


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
