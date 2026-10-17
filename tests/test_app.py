from fastapi.testclient import TestClient
from app.main import app
from app.services.renderer import PRESETS
from app.services.rights import source_is_publishable
from app.config import Settings
from app.models import Source
from app.schemas import PublishRequest
import pytest

client = TestClient(app)

def test_health_and_dashboard():
    assert client.get("/health").json()["service"] == "vyralx"
    assert "VyralX Control Room" in client.get("/").text

def test_render_presets_are_defined():
    assert PRESETS["shorts"] == (1080, 1920)
    assert PRESETS["long"] == (1920, 1080)
    assert PRESETS["square"] == (1080, 1080)

def test_rights_gate_fails_closed():
    assert not source_is_publishable(None)
    assert not source_is_publishable(Source(title="unverified", rights_verified=False))
    assert not source_is_publishable(Source(title="no evidence", rights_verified=True))
    assert source_is_publishable(Source(title="licensed", rights_verified=True, license_name="CC BY 4.0"))

def test_invalid_source_rejected_without_auth_in_dev():
    response = client.post("/api/sources", json={"title": ""})
    assert response.status_code == 422


def test_discovery_errors_do_not_leak_provider_secrets(monkeypatch):
    from app import main as main_module

    def fail_discovery(*args, **kwargs):
        raise RuntimeError("upstream URL contains key=do-not-leak")

    monkeypatch.setattr(main_module, "discover_youtube_videos", fail_discovery)
    response = client.post("/api/discover", json={"query": "test"})
    assert response.status_code == 502
    assert "do-not-leak" not in response.text
    assert "check server logs" in response.text


def test_production_rejects_default_api_key():
    with pytest.raises(ValueError, match="unique API_KEY"):
        Settings(app_env="production")


def test_publish_request_binds_render_and_uses_configured_privacy_default():
    request = PublishRequest(asset_id=4, render_job_id=12, title="Demo Short")
    assert request.render_job_id == 12
    assert request.privacy_status is None
