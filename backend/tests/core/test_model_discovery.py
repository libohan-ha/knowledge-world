"""Model discovery uses caller credentials without storing them or locking writes."""
import httpx
import pytest


def test_discover_unsaved_models_is_private_and_releases_write_transaction(h, monkeypatch):
    def get(client, url, **kwargs):
        assert url == "http://relay.invalid/v1/models"
        assert kwargs["headers"]["Authorization"] == "Bearer synthetic-discovery-key"
        with h.db.transaction(True, h.owner) as c:
            c.audit("discovery.unlocked", "test", "read")
        return httpx.Response(200, json={"data": [{"id": "z-model"}, {"id": "a-model"}, {"id": "a-model"}]})
    monkeypatch.setattr(httpx.Client, "get", get)
    response = h.request("POST", "/providers/chat/models", {"base_url": "http://relay.invalid/v1/", "api_key": "synthetic-discovery-key"}, status=200)
    assert response.json()["data"] == {"models": [{"id": "a-model"}, {"id": "z-model"}]}
    assert response.headers["cache-control"] == "no-store"
    assert "synthetic-discovery-key" not in response.text
    assert h.scalar("SELECT count(*) FROM provider_configs") == 0


def test_saved_key_is_reused_only_for_same_service(h, monkeypatch):
    monkeypatch.setenv("AI_DISCOVERY_TEST", "synthetic-saved-key")
    saved = h.request("PUT", "/providers/chat", {"base_url": "http://relay.invalid/v1", "model": "old", "secret_env": "AI_DISCOVERY_TEST"}, status=200).json()["data"]
    calls = []
    def get(client, url, **kwargs):
        calls.append(url)
        assert kwargs["headers"]["Authorization"] == "Bearer synthetic-saved-key"
        return httpx.Response(200, json={"data": [{"id": "new"}]})
    monkeypatch.setattr(httpx.Client, "get", get)
    h.request("POST", "/providers/chat/models", {"base_url": saved["base_url"], "expected_version": saved["version"]}, status=200)
    response = h.request("POST", "/providers/chat/models", {"base_url": "http://another.invalid/v1", "expected_version": saved["version"]}, status=409)
    assert response.json()["error"]["code"] == "CREDENTIAL_REQUIRED"
    assert len(calls) == 1
    assert h.scalar("SELECT model FROM provider_configs") == "old"


@pytest.mark.parametrize("status,payload,code", [(401, {"error": "synthetic-key"}, "PROVIDER_AUTH_FAILED"), (200, {"models": []}, "PROVIDER_INVALID_RESPONSE"), (302, {}, "PROVIDER_REDIRECT_REJECTED")])
def test_discovery_errors_are_actionable_and_do_not_echo_upstream(h, monkeypatch, status, payload, code):
    monkeypatch.setattr(httpx.Client, "get", lambda *a, **k: httpx.Response(status, json=payload))
    response = h.request("POST", "/providers/chat/models", {"base_url": "https://relay.invalid/v1", "api_key": "synthetic-key"}, status=502)
    assert response.json()["error"]["code"] == code
    assert "synthetic-key" not in response.text


def test_discovery_checks_session_again_after_network(h, monkeypatch):
    def get(*args, **kwargs):
        with h.db.transaction(True, h.owner) as c:
            c.execute("UPDATE auth_sessions SET revoked_at=:now", {"now": c.now})
        return httpx.Response(200, json={"data": [{"id": "private-model"}]})
    monkeypatch.setattr(httpx.Client, "get", get)
    h.request("POST", "/providers/chat/models", {"base_url": "https://relay.invalid/v1", "api_key": "synthetic-key"}, status=401)
