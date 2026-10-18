from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Load the CLI by file path: `scripts` is intentionally not installed as an app package,
# and GitHub Actions may run pytest with only the installed project on sys.path.
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mesh_preflight.py"
_SPEC = importlib.util.spec_from_file_location("vyralx_mesh_preflight", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
mesh_preflight = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = mesh_preflight
_SPEC.loader.exec_module(mesh_preflight)


def _settings(**overrides):
    values = {
        "friday_url": "",
        "friday_api_key": "",
        "inference_url": "",
        "inference_api_key": "",
        "intelx_url": "",
        "intelx_api_key": "",
        "memora_url": "",
        "memora_api_key": "",
        "sentinel_url": "",
        "sentinel_api_key": "",
        "memora_read_enabled": False,
        "memora_write_enabled": False,
        "sentinel_required_for_publish": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _healthy(name, *, timeout_seconds=3.0):
    return {"name": name, "configured": True, "reachable": True, "status": "ok", "http_status": 200}


def test_empty_optional_mesh_is_reported_without_failing(monkeypatch):
    monkeypatch.setattr(mesh_preflight, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        mesh_preflight, "peer_health", lambda *args, **kwargs: pytest.fail("no peer is configured")
    )
    report = mesh_preflight.run_preflight()
    assert report["overall_status"] == "warning"
    assert report["summary"]["skipped"] == len(mesh_preflight.PEER_NAMES)
    assert report["read_only"] is True


def test_required_unconfigured_peer_fails_preflight(monkeypatch):
    monkeypatch.setattr(mesh_preflight, "get_settings", lambda: _settings())
    report = mesh_preflight.run_preflight(required_peers={"inference"})
    check = next(item for item in report["checks"] if item["check"] == "inference.configuration")
    assert report["overall_status"] == "failed"
    assert check["status"] == "failed"
    assert check["required"] is True


def test_partial_url_and_key_is_a_configuration_failure(monkeypatch):
    settings = _settings(memora_url="https://memora.internal")
    monkeypatch.setattr(mesh_preflight, "get_settings", lambda: settings)
    monkeypatch.setattr(
        mesh_preflight,
        "peer_health",
        lambda *args, **kwargs: pytest.fail("partial config reached network"),
    )
    report = mesh_preflight.run_preflight()
    check = next(item for item in report["checks"] if item["check"] == "memora.configuration")
    assert report["overall_status"] == "failed"
    assert "both be configured" in check["message"]


def test_peer_url_with_credentials_is_rejected(monkeypatch):
    settings = _settings(
        intelx_url="https://user:password@intelx.internal", intelx_api_key="not-logged"
    )
    monkeypatch.setattr(mesh_preflight, "get_settings", lambda: settings)
    monkeypatch.setattr(
        mesh_preflight,
        "peer_health",
        lambda *args, **kwargs: pytest.fail("unsafe URL reached network"),
    )
    report = mesh_preflight.run_preflight()
    check = next(item for item in report["checks"] if item["check"] == "intelx.configuration")
    assert check["status"] == "failed"
    assert "user" not in json.dumps(report)
    assert "password" not in json.dumps(report)


@pytest.mark.parametrize("url", ["https://intelx.internal:not-a-port", "https://intelx.internal:0"])
def test_invalid_port_is_rejected_before_network_call(monkeypatch, url):
    settings = _settings(intelx_url=url, intelx_api_key="not-logged")
    monkeypatch.setattr(mesh_preflight, "get_settings", lambda: settings)
    monkeypatch.setattr(
        mesh_preflight,
        "peer_health",
        lambda *args, **kwargs: pytest.fail("invalid port reached network"),
    )
    report = mesh_preflight.run_preflight()
    check = next(item for item in report["checks"] if item["check"] == "intelx.configuration")
    assert check["status"] == "failed"


def test_intelx_probe_uses_read_only_contract_and_sanitizes_results(monkeypatch):
    settings = _settings(intelx_url="https://intelx.internal", intelx_api_key="secret")
    captured = {}
    monkeypatch.setattr(mesh_preflight, "get_settings", lambda: settings)
    monkeypatch.setattr(mesh_preflight, "peer_health", _healthy)

    def fake_get(peer, path, params, *, timeout_seconds):
        captured.update(peer=peer, path=path, params=params, timeout=timeout_seconds)
        return {"reports": []}

    monkeypatch.setattr(mesh_preflight, "get_peer_json", fake_get)
    report = mesh_preflight.run_preflight(probes={"intelx"}, timeout_seconds=2.5)
    check = next(item for item in report["checks"] if item["check"] == "intelx.probe")
    assert check["status"] == "ok"
    assert check["records_returned"] == 0
    assert check["mutating"] is False
    assert captured == {
        "peer": "intelx",
        "path": "/api/v1/research/query",
        "params": {"sector": "vyralx deployment preflight", "limit": 1},
        "timeout": 2.5,
    }
    assert "secret" not in json.dumps(report)


def test_memora_probe_uses_private_namespace_and_never_writes(monkeypatch):
    settings = _settings(memora_url="https://memora.internal", memora_api_key="secret")
    captured = {}
    monkeypatch.setattr(mesh_preflight, "get_settings", lambda: settings)
    monkeypatch.setattr(mesh_preflight, "peer_health", _healthy)

    def fake_get(peer, path, params, *, timeout_seconds):
        captured.update(peer=peer, path=path, params=params)
        return {"success": True, "result": {"memories": []}}

    monkeypatch.setattr(mesh_preflight, "get_peer_json", fake_get)
    report = mesh_preflight.run_preflight(probes={"memora"})
    check = next(item for item in report["checks"] if item["check"] == "memora.probe")
    assert report["overall_status"] == "warning"
    assert check["status"] == "ok"
    assert check["mutating"] is False
    assert captured["path"] == "/v1/memories/search"
    assert captured["params"]["namespace_path"] == "memora://vyralx/private"
    assert "content_text" not in json.dumps(captured)


def test_provider_error_envelope_does_not_leak_body(monkeypatch):
    settings = _settings(intelx_url="https://intelx.internal", intelx_api_key="secret")
    monkeypatch.setattr(mesh_preflight, "get_settings", lambda: settings)
    monkeypatch.setattr(mesh_preflight, "peer_health", _healthy)
    monkeypatch.setattr(
        mesh_preflight,
        "get_peer_json",
        lambda *args, **kwargs: {"status": "failed", "error": "provider-private error response"},
    )
    report = mesh_preflight.run_preflight(probes={"intelx"})
    check = next(item for item in report["checks"] if item["check"] == "intelx.probe")
    assert report["overall_status"] == "failed"
    assert check["status"] == "failed"
    assert "provider-private error response" not in json.dumps(report)


def test_inference_generation_is_explicit_and_discards_content(monkeypatch):
    settings = _settings(inference_url="https://inference.internal", inference_api_key="secret")
    captured = {}
    monkeypatch.setattr(mesh_preflight, "get_settings", lambda: settings)
    monkeypatch.setattr(mesh_preflight, "peer_health", _healthy)

    def fake_generate(topic, **kwargs):
        captured.update(topic=topic, kwargs=kwargs)
        return {"script": "do not output this generated script"}

    monkeypatch.setattr(mesh_preflight, "generate_content_pack", fake_generate)
    report = mesh_preflight.run_preflight(probe_inference=True)
    check = next(item for item in report["checks"] if item["check"] == "inference.generation")
    assert report["overall_status"] == "warning"
    assert check["status"] == "ok"
    assert check["generated_content_discarded"] is True
    assert captured == {
        "topic": "VyralX deployment preflight",
        "kwargs": {"video_format": "shorts", "target_seconds": 15},
    }
    assert "do not output" not in json.dumps(report)


def test_mandatory_incompatible_sentinel_contract_blocks_preflight(monkeypatch):
    settings = _settings(
        sentinel_url="https://sentinel.internal",
        sentinel_api_key="secret",
        sentinel_required_for_publish=True,
    )
    monkeypatch.setattr(mesh_preflight, "get_settings", lambda: settings)
    monkeypatch.setattr(mesh_preflight, "peer_health", _healthy)
    report = mesh_preflight.run_preflight()
    check = next(item for item in report["checks"] if item["check"] == "sentinel.publish_policy")
    assert report["overall_status"] == "failed"
    assert check["status"] == "failed"
    assert "youtube.publish" in check["message"]


def test_memora_features_make_memora_required(monkeypatch):
    settings = _settings(memora_read_enabled=True)
    monkeypatch.setattr(mesh_preflight, "get_settings", lambda: settings)
    report = mesh_preflight.run_preflight()
    check = next(item for item in report["checks"] if item["check"] == "memora.configuration")
    assert check["status"] == "failed"
    assert check["required"] is True


def test_cli_rejects_out_of_range_timeout():
    with pytest.raises(SystemExit) as exc:
        mesh_preflight.main(["--timeout", "0"])
    assert exc.value.code == 2
