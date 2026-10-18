from __future__ import annotations

from types import SimpleNamespace

from app.services import peers


def _settings():
    return SimpleNamespace(
        friday_url="", friday_api_key="",
        inference_url="", inference_api_key="",
        intelx_url="", intelx_api_key="",
        memora_url="http://memora:8000/", memora_api_key="memora-test-key",
        sentinel_url="", sentinel_api_key="",
    )


def test_memora_search_uses_vyralx_identity_key_and_exact_v1_route(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return SimpleNamespace(
            content=b'{"items":[]}',
            json=lambda: {"items": []},
            raise_for_status=lambda: None,
        )

    monkeypatch.setattr(peers, "get_settings", _settings)
    monkeypatch.setattr(peers.httpx, "get", fake_get)

    result = peers.get_peer_json(
        "memora",
        "/v1/memories/search",
        {
            "q": "solar energy",
            "namespace_path": "memora://vyralx/private",
            "limit": 5,
            "min_score": 0.2,
        },
    )

    assert result == {"items": []}
    assert captured["url"] == "http://memora:8000/v1/memories/search"
    assert captured["headers"]["X-Agent-Name"] == "vyralx"
    assert captured["headers"]["X-API-Key"] == "memora-test-key"
    assert captured["headers"]["Authorization"] == "Bearer memora-test-key"
    assert captured["params"]["namespace_path"] == "memora://vyralx/private"
    assert captured["follow_redirects"] is False


def test_memora_completion_write_uses_vyralx_identity_and_never_logs_key(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return SimpleNamespace(
            content=b'{"id":"memory-123"}',
            json=lambda: {"id": "memory-123"},
            raise_for_status=lambda: None,
        )

    monkeypatch.setattr(peers, "get_settings", _settings)
    monkeypatch.setattr(peers.httpx, "post", fake_post)

    result = peers.post_peer_json(
        "memora",
        "/v1/memories",
        {
            "target_namespace_path": "memora://vyralx/private",
            "content_text": "test project summary",
            "source": "vyralx",
        },
    )

    assert result == {"id": "memory-123"}
    assert captured["url"] == "http://memora:8000/v1/memories"
    assert captured["headers"]["X-Agent-Name"] == "vyralx"
    assert captured["headers"]["X-API-Key"] == "memora-test-key"
    assert captured["headers"]["Authorization"] == "Bearer memora-test-key"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["json"]["target_namespace_path"] == "memora://vyralx/private"
    assert captured["follow_redirects"] is False
