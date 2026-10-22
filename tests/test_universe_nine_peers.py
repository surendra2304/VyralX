"""Tests for all 9 FRIDAY Universe peer agent integrations and endpoints."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.datax import stream_datax_telemetry
from app.services.echo import dispatch_echo_notification
from app.services.gatekeeper import verify_mesh_authorization
from app.services.mediax import register_mediax_asset
from app.services.peers import configured_peers, peer_health


def test_configured_peers_all_nine(monkeypatch):
    settings = get_settings()
    nine_agents = {
        "friday": ("http://friday.mesh:8001", "key-friday"),
        "inference": ("http://inference.mesh:8002", "key-inference"),
        "intelx": ("http://intelx.mesh:8003", "key-intelx"),
        "memora": ("http://memora.mesh:8004", "key-memora"),
        "sentinel": ("http://sentinel.mesh:8005", "key-sentinel"),
        "echo": ("http://echo.mesh:8006", "key-echo"),
        "mediax": ("http://mediax.mesh:8007", "key-mediax"),
        "datax": ("http://datax.mesh:8008", "key-datax"),
        "gatekeeper": ("http://gatekeeper.mesh:8009", "key-gatekeeper"),
    }
    for agent, (url, key) in nine_agents.items():
        monkeypatch.setattr(settings, f"{agent}_url", url)
        monkeypatch.setattr(settings, f"{agent}_api_key", key)

    peers = configured_peers()
    for agent in nine_agents:
        assert agent in peers
        assert peers[agent].base_url == nine_agents[agent][0]
        assert peers[agent].api_key == nine_agents[agent][1]


def test_peer_health_unconfigured():
    health = peer_health("unconfigured_agent")
    assert health["configured"] is False
    assert health["reachable"] is False
    assert health["status"] == "not_configured"


def test_peer_health_reachable(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "echo_url", "http://echo.mesh:8006")
    monkeypatch.setattr(settings, "echo_api_key", "key-echo")

    mock_resp = MagicMock(is_success=True, status_code=200)
    with patch("httpx.get", return_value=mock_resp):
        health = peer_health("echo")
        assert health["configured"] is True
        assert health["reachable"] is True
        assert health["status"] == "ok"


def test_echo_notification_dispatch_skipped_when_disabled(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "echo_notifications_enabled", False)
    monkeypatch.setattr(settings, "echo_url", "")
    monkeypatch.setattr(settings, "echo_api_key", "")

    result = dispatch_echo_notification("test.event", "Test Title", {"foo": "bar"})
    assert result["status"] == "skipped"
    assert result["reason"] == "not_configured"


def test_echo_notification_dispatch_success(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "echo_url", "http://echo.mesh:8006")
    monkeypatch.setattr(settings, "echo_api_key", "key-echo")
    monkeypatch.setattr(settings, "echo_notifications_enabled", True)

    with patch("app.services.echo.post_peer_json", return_value={"event_id": "echo-123"}) as mock_post:
        result = dispatch_echo_notification("video.rendered", "Project Rendered", {"project_id": 42})
        assert result["status"] == "dispatched"
        assert result["response"]["event_id"] == "echo-123"
        mock_post.assert_called_once()
        args = mock_post.call_args[0]
        assert args[0] == "echo"
        assert args[1] == "/v1/notifications"
        assert args[2]["event_type"] == "video.rendered"


def test_echo_notification_dispatch_error(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "echo_url", "http://echo.mesh:8006")
    monkeypatch.setattr(settings, "echo_api_key", "key-echo")
    monkeypatch.setattr(settings, "echo_notifications_enabled", True)

    with patch("app.services.echo.post_peer_json", side_effect=RuntimeError("connection refused")):
        result = dispatch_echo_notification("video.failed", "Render Failed", {"error": "boom"})
        assert result["status"] == "failed"
        assert "RuntimeError" in result["error"]


def test_mediax_asset_registration(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "mediax_url", "http://mediax.mesh:8007")
    monkeypatch.setattr(settings, "mediax_api_key", "key-mediax")
    monkeypatch.setattr(settings, "mediax_registry_enabled", True)

    media_file = tmp_path / "rendered.mp4"
    media_file.write_bytes(b"test video payload")

    with patch("app.services.mediax.post_peer_json", return_value={"asset_hash": "abc", "status": "indexed"}) as mock_post:
        result = register_mediax_asset(101, media_file, {"format": "shorts"})
        assert result["status"] == "registered"
        mock_post.assert_called_once()
        args = mock_post.call_args[0]
        assert args[0] == "mediax"
        assert args[1] == "/v1/assets/register"
        assert args[2]["internal_asset_id"] == 101


def test_mediax_asset_registration_skipped(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "mediax_registry_enabled", False)
    monkeypatch.setattr(settings, "mediax_url", "")
    monkeypatch.setattr(settings, "mediax_api_key", "")

    result = register_mediax_asset(101, "dummy.mp4", {})
    assert result["status"] == "skipped"


def test_datax_telemetry_dispatch(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "datax_url", "http://datax.mesh:8008")
    monkeypatch.setattr(settings, "datax_api_key", "key-datax")
    monkeypatch.setattr(settings, "datax_telemetry_enabled", True)

    with patch("app.services.datax.post_peer_json", return_value={"ingested": True}) as mock_post:
        result = stream_datax_telemetry("render_benchmarks", {"fps": 60, "duration": 15.0}, project_id=5)
        assert result["status"] == "streamed"
        mock_post.assert_called_once()
        args = mock_post.call_args[0]
        assert args[0] == "datax"
        assert args[1] == "/v1/telemetry/ingest"
        assert args[2]["project_id"] == 5


def test_datax_telemetry_skipped(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "datax_telemetry_enabled", False)
    monkeypatch.setattr(settings, "datax_url", "")
    monkeypatch.setattr(settings, "datax_api_key", "")

    result = stream_datax_telemetry("render_benchmarks", {})
    assert result["status"] == "skipped"


def test_gatekeeper_verification(monkeypatch):
    settings = get_settings()
    # Unconfigured fallback
    monkeypatch.setattr(settings, "gatekeeper_url", "")
    monkeypatch.setattr(settings, "gatekeeper_api_key", "")
    res = verify_mesh_authorization("local-token", "render")
    assert res["authorized"] is True
    assert res["source"] == "local_fallback"

    # Configured peer call
    monkeypatch.setattr(settings, "gatekeeper_url", "http://gatekeeper.mesh:8009")
    monkeypatch.setattr(settings, "gatekeeper_api_key", "key-gatekeeper")
    with patch("app.services.gatekeeper.post_peer_json", return_value={"authorized": True, "claims": {"sub": "friday"}}):
        res = verify_mesh_authorization("bearer-mesh-token", "publish")
        assert res["authorized"] is True

    with patch("app.services.gatekeeper.post_peer_json", return_value={"authorized": False, "reason": "expired"}):
        res = verify_mesh_authorization("expired-token", "publish")
        assert res["authorized"] is False


def test_api_peers_endpoint():
    settings = get_settings()
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    def fake_health(name, timeout_seconds=3.0):
        return {"name": name, "configured": True, "reachable": True, "status": "ok"}

    with patch("app.main.peer_health", side_effect=fake_health):
        resp = client.get("/api/peers", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["total_peers"] == 13
        assert "peers" in data
        peers = data["peers"]
        for expected in (
            "friday", "inference", "intelx", "memora", "sentinel",
            "stratex", "forge", "cortex", "futuris",
            "echo", "mediax", "datax", "gatekeeper",
        ):
            assert expected in peers
            assert peers[expected]["status"] == "ok"


def test_api_agents_health_endpoint():
    settings = get_settings()
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    def fake_health(name, timeout_seconds=3.0):
        return {"name": name, "configured": True, "reachable": True, "status": "ok"}

    with patch("app.main.peer_health", side_effect=fake_health):
        resp = client.get("/api/agents/health", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        for expected in (
            "friday", "inference", "intelx", "memora", "sentinel",
            "stratex", "forge", "cortex", "futuris",
            "echo", "mediax", "datax", "gatekeeper",
        ):
            assert expected in data
            assert data[expected]["status"] == "ok"


def test_api_integrations_endpoint_includes_mesh_peers():
    settings = get_settings()
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    resp = client.get("/api/integrations", headers=headers)
    assert resp.status_code == 200
    providers = resp.json().get("providers", {})
    assert "echo" in providers
    assert "mediax" in providers
    assert "datax" in providers
    assert "gatekeeper" in providers
