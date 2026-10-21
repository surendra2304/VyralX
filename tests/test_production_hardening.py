"""Regression tests for production workflow hardening."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.database import SessionLocal
from app.models import Asset, PublishJob, RenderJob, Source
from app.services.captions import segment_script, write_srt
from app.services.content import _extract_json, generate_content_pack
from app.services.intelx import normalize_intelx_reports
from app.services.rights import (
    append_stock_attribution,
    find_repeat_use_blockers,
    source_is_publishable,
    source_reuse_identity,
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


@pytest.mark.parametrize(
    "media_url,license_url",
    [
        ("https://www.pexels.com@evil.example/video/123/", "https://www.pexels.com/license/"),
        ("https://user@www.pexels.com/video/123/", "https://www.pexels.com/license/"),
        ("https://www.pexels.com:444/video/123/", "https://www.pexels.com/license/"),
        ("https://www.pexels.com:notaport/video/123/", "https://www.pexels.com/license/"),
        ("https://www.pexels.com:/video/123/", "https://www.pexels.com/license/"),
        ("https://www.pexels.com/video/123/", "https://www.pexels.com.evil.example/license/"),
        ("https://www.pexels.com/video/123/", "https://user@www.pexels.com/license/"),
        ("https://www.pexels.com/video/123/", "https://www.pexels.com:444/license/"),
        ("https://www.pexels.com/video/123/", "https://www.pexels.com:bad/license/"),
        ("https://www.pexels.com/video/123/", "https://www.pexels.com:/license/"),
        ("http://www.pexels.com/video/123/", "https://www.pexels.com/license/"),
        ("https://www.pexels.com.evil.example/video/123/", "https://www.pexels.com/license/"),
        ("https://www.pexels.com/video/", "https://www.pexels.com/license/"),
        ("https://www.pexels.com.evil.example/video/123/", "https://www.pexels.com/license/"),
    ],
)
def test_pexels_rights_gate_rejects_malformed_or_untrusted_url_authority(media_url, license_url):
    source = Source(
        title="Forged provenance",
        platform="pexels",
        source_url=media_url,
        rights_verified=True,
        license_name="Pexels Content License",
        permission_reference=license_url,
    )

    assert not source_is_publishable(source)


@pytest.mark.parametrize(
    "media_url,license_url",
    [
        ("https://www.pexels.com/video/123/", "https://www.pexels.com/license/"),
        ("https://pexels.com:443/video/123/", "https://pexels.com:443/license/"),
    ],
)
def test_pexels_rights_gate_accepts_official_https_urls_and_default_port(media_url, license_url):
    source = Source(
        title="Official provenance",
        platform="pexels",
        source_url=media_url,
        rights_verified=True,
        license_name="Pexels Content License",
        permission_reference=license_url,
    )

    assert source_is_publishable(source)


def test_stock_credits_fail_closed_when_full_urls_do_not_fit():
    source = SimpleNamespace(
        platform="pexels",
        source_url="https://www.pexels.com/video/" + ("x" * 2600),
        creator="Creator",
        permission_reference="https://www.pexels.com/license/" + ("y" * 2600),
    )
    with pytest.raises(ValueError, match="attribution exceeds"):
        append_stock_attribution("Short intro", [(SimpleNamespace(id=1), source)])


def test_stock_attribution_respects_utf8_byte_budget():
    source = SimpleNamespace(
        platform="pexels",
        source_url="https://www.pexels.com/video/123456/",
        creator="Creator",
        permission_reference="https://www.pexels.com/license/",
    )
    description = append_stock_attribution("é" * 2490, [(SimpleNamespace(id=1), source)])

    assert len(description.encode("utf-8")) <= 5000
    assert "Stock footage credits:" in description
    assert "- Creator (Pexels): https://www.pexels.com/video/123456/" in description
    assert "�" not in description


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


def test_intelx_normalization_unwraps_nested_provider_envelopes_and_rejects_no_signal():
    reports = normalize_intelx_reports(
        {
            "status": "success",
            "result": {
                "reports": [
                    {
                        "report_id": "ix-solar-nested",
                        "title": "Solar power market update",
                        "summary": "Solar generation capacity expanded this year.",
                    },
                    {
                        "report_id": "ix-no-signal",
                        "title": "---",
                        "summary": "!!!",
                    },
                ]
            },
        },
        "solar power",
    )

    assert [item["report_id"] for item in reports] == ["ix-solar-nested"]


def test_intelx_fetch_reports_and_status_from_live_style_envelope(monkeypatch):
    from app.services import project_pipeline

    monkeypatch.setattr(project_pipeline, "configured_peers", lambda: {"intelx"})
    monkeypatch.setattr(
        project_pipeline,
        "get_peer_json",
        lambda *args, **kwargs: {
            "result": {
                "reports": [
                    {
                        "report_id": "ix-solar-fetch",
                        "title": "Solar power trends",
                        "summary": "Solar capacity grew over the past year.",
                        "source_url": "https://intelx.example/reports/ix-solar-fetch",
                    },
                    {
                        "report_id": "ix-basketball-fetch",
                        "title": "Basketball championship",
                        "summary": "Teams competed in the finals.",
                    },
                ]
            }
        },
    )

    reports, status = project_pipeline._fetch_intelx_research(
        SimpleNamespace(id=72, topic="Solar power")
    )

    assert status == "used"
    assert [item["report_id"] for item in reports] == ["ix-solar-fetch"]
    assert reports[0]["source_url"] == "https://intelx.example/reports/ix-solar-fetch"


def test_intelx_fetch_reports_not_configured_and_unavailable(monkeypatch):
    from app.services import project_pipeline

    project = SimpleNamespace(id=73, topic="Solar power")
    monkeypatch.setattr(project_pipeline, "configured_peers", lambda: set())
    assert project_pipeline._fetch_intelx_research(project) == ([], "not_configured")

    monkeypatch.setattr(project_pipeline, "configured_peers", lambda: {"intelx"})
    def unavailable(*args, **kwargs):
        raise RuntimeError("provider exception must not be persisted")
    monkeypatch.setattr(project_pipeline, "get_peer_json", unavailable)
    assert project_pipeline._fetch_intelx_research(project) == ([], "unavailable")


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

def test_source_reuse_identity_ignores_tracking_and_fragment():
    first = Source(
        id=1, title="License record", platform="manual",
        source_url="https://media.example/license/video.mp4?utm_source=one&v=2#player",
    )
    second = Source(
        id=2, title="Same licensed media", platform="manual",
        source_url="https://MEDIA.example/license/video.mp4?v=2&utm_source=two",
    )

    assert source_reuse_identity(first) == source_reuse_identity(second)


def test_repeat_use_blocker_detects_prior_upload_and_respects_explicit_review():
    from uuid import uuid4

    suffix = uuid4().hex[:12]
    with SessionLocal() as db:
        previously_used = Source(
            title="Published source " + suffix,
            source_url=f"https://media.example/licensed/{suffix}?utm_source=old",
            platform="manual",
            creator="Owner",
            license_name="Written permission",
            permission_reference="permission-reference-" + suffix,
            rights_verified=True,
            repeat_use_allowed=False,
        )
        current = Source(
            title="Current source " + suffix,
            source_url=f"https://media.example/licensed/{suffix}?utm_source=new#preview",
            platform="manual",
            creator="Owner",
            license_name="Written permission",
            permission_reference="permission-reference-" + suffix,
            rights_verified=True,
            repeat_use_allowed=False,
        )
        db.add_all([previously_used, current])
        db.flush()
        old_asset = Asset(
            source_id=previously_used.id, title="Prior published asset " + suffix,
            file_path="/tmp/not-used-" + suffix + ".mp4", rights_verified=True,
        )
        current_asset = Asset(
            source_id=current.id, title="New reuse asset " + suffix,
            file_path="/tmp/not-used-current-" + suffix + ".mp4", rights_verified=True,
        )
        db.add_all([old_asset, current_asset])
        db.flush()
        old_render = RenderJob(
            asset_id=old_asset.id, preset="shorts", status="completed",
            output_path="/tmp/not-rendered-" + suffix + ".mp4", options_json="{}",
        )
        db.add(old_render)
        db.flush()
        published = PublishJob(
            asset_id=old_asset.id, render_job_id=old_render.id,
            title="Prior uploaded " + suffix, status="uploaded",
            youtube_video_id="video_" + suffix,
        )
        db.add(published)
        db.flush()

        blockers = find_repeat_use_blockers([(current_asset, current)], db)
        assert len(blockers) == 1
        assert blockers[0]["source_id"] == current.id

        current.repeat_use_allowed = True
        current.repeat_use_reviewed_at = current.created_at
        current.repeat_use_review_notes = "Reviewed the applicable written permission for repeated use."
        assert find_repeat_use_blockers([(current_asset, current)], db) == []

        db.delete(published)
        db.delete(old_render)
        db.delete(old_asset)
        db.delete(current_asset)
        db.delete(previously_used)
        db.delete(current)
        db.commit()

@pytest.mark.parametrize(
    "source_url",
    [
        "https://[malformed-host/media",
        "https://media.example:not-a-port/clip?q=1#preview",
    ],
)
def test_source_reuse_identity_handles_malformed_url_authorities(source_url: str):
    source = Source(
        title="Malformed but stable source identity",
        source_url=source_url,
        platform="manual",
    )

    identity = source_reuse_identity(source)

    assert identity is not None
    assert identity[0] == "url"
    assert identity[1] == source_url.split("#", 1)[0].rstrip("/")


@pytest.mark.parametrize(
    "media_url",
    [
        "https://www.pexels.com/video/../license/",
        "https://www.pexels.com/video/%2e%2e/license/",
        "https://www.pexels.com/video/%252e%252e/license/",
        "https://www.pexels.com/video/%25252e%25252e/license/",
        "https://www.pexels.com/video/%2E%2E%2fvideo/123/",
        "https://www.pexels.com/video/%5c..%5clicense/",
        "https://www.pexels.com/video//123/",
        "https://www.pexels.com/video/slug/nested/",
    ],
)
def test_rights_gate_rejects_pexels_video_path_traversal_and_ambiguous_paths(
    media_url: str,
):
    source = Source(
        title="Ambiguous Pexels path",
        platform="pexels",
        source_url=media_url,
        rights_verified=True,
        license_name="Pexels Content License",
        permission_reference="https://www.pexels.com/license/",
    )
    assert not source_is_publishable(source)

def test_rights_gate_accepts_normal_pexels_video_path():
    source = Source(
        title="Valid Pexels video page",
        platform="pexels",
        source_url="https://www.pexels.com/video/123456-example-clip/",
        rights_verified=True,
        license_name="Pexels Content License",
        permission_reference="https://www.pexels.com/license/",
    )
    assert source_is_publishable(source)
