from __future__ import annotations

import httpx
import pytest

from app.services import peers


def _peer() -> peers.Peer:
    return peers.Peer(
        name="memora",
        base_url="http://memora:8000/",
        api_key="test-secret-that-is-never-logged",
    )


def test_post_peer_json_uses_vyralx_identity_and_does_not_follow_redirects(monkeypatch):
    peer = _peer()
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        request = httpx.Request("POST", url)
        return httpx.Response(201, json={"id": "memory-123"}, request=request)

    monkeypatch.setattr(peers, "configured_peers", lambda: {"memora": peer})
    monkeypatch.setattr(peers.httpx, "post", fake_post)

    result = peers.post_peer_json(
        "memora",
        "/v1/memories",
        {"content_text": "safe test record"},
        timeout_seconds=4.5,
    )

    assert result == {"id": "memory-123"}
    assert captured["url"] == "http://memora:8000/v1/memories"
    assert captured["json"] == {"content_text": "safe test record"}
    assert captured["timeout"] == 4.5
    assert captured["follow_redirects"] is False
    assert captured["headers"]["Authorization"] == "Bearer test-secret-that-is-never-logged"
    assert captured["headers"]["X-API-Key"] == "test-secret-that-is-never-logged"
    assert captured["headers"]["X-Agent-Name"] == "vyralx"
    assert captured["headers"]["Content-Type"] == "application/json"


def test_get_peer_json_preserves_query_and_vyralx_auth_headers(monkeypatch):
    peer = _peer()
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            json=[{"id": "memory-123", "namespace_path": "memora://vyralx/private"}],
            request=request,
        )

    monkeypatch.setattr(peers, "configured_peers", lambda: {"memora": peer})
    monkeypatch.setattr(peers.httpx, "get", fake_get)

    result = peers.get_peer_json(
        "memora",
        "/v1/memories/search",
        {"namespace_path": "memora://vyralx/private", "limit": 5},
        timeout_seconds=3.0,
    )

    assert result == [{"id": "memory-123", "namespace_path": "memora://vyralx/private"}]
    assert captured["url"] == "http://memora:8000/v1/memories/search"
    assert captured["params"] == {"namespace_path": "memora://vyralx/private", "limit": 5}
    assert captured["timeout"] == 3.0
    assert captured["follow_redirects"] is False
    assert captured["headers"]["X-Agent-Name"] == "vyralx"
    assert captured["headers"]["X-API-Key"] == "test-secret-that-is-never-logged"
    assert captured["headers"]["Authorization"] == "Bearer test-secret-that-is-never-logged"


@pytest.mark.parametrize(
    "path",
    [
        "v1/memories",
        "//attacker.invalid/v1/memories",
        "/https://attacker.invalid/v1/memories",
        "/v1/../secrets",
    ],
)
def test_peer_clients_reject_unsafe_paths_before_network_call(monkeypatch, path):
    monkeypatch.setattr(peers, "configured_peers", lambda: {"memora": _peer()})

    def forbidden(*args, **kwargs):
        raise AssertionError("unsafe path reached the network client")

    monkeypatch.setattr(peers.httpx, "post", forbidden)
    monkeypatch.setattr(peers.httpx, "get", forbidden)

    with pytest.raises(ValueError):
        peers.post_peer_json("memora", path, {})
    with pytest.raises(ValueError):
        peers.get_peer_json("memora", path)


def test_peer_response_errors_do_not_leak_provider_body(monkeypatch):
    peer = _peer()

    def fake_post(url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(
            403,
            json={"detail": "sensitive provider diagnostics must not appear in logs"},
            request=request,
        )

    monkeypatch.setattr(peers, "configured_peers", lambda: {"memora": peer})
    monkeypatch.setattr(peers.httpx, "post", fake_post)

    with pytest.raises(RuntimeError) as exc:
        peers.post_peer_json("memora", "/v1/memories", {})
    assert "HTTP 403" in str(exc.value)
    assert "sensitive provider diagnostics" not in str(exc.value)


def test_unconfigured_peer_fails_closed_without_network_call(monkeypatch):
    monkeypatch.setattr(peers, "configured_peers", lambda: {})

    def forbidden(*args, **kwargs):
        raise AssertionError("unconfigured peer reached the network client")

    monkeypatch.setattr(peers.httpx, "post", forbidden)
    with pytest.raises(RuntimeError, match="not configured"):
        peers.post_peer_json("memora", "/v1/memories", {})
