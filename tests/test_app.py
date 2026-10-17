from fastapi.testclient import TestClient
from app.main import app
from app.services.renderer import PRESETS
from app.services.rights import source_is_publishable
from app.models import Source

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
