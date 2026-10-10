"""Public provider settings accept user-hosted services without exposing keys."""
import pytest


def test_http_provider_can_be_saved_and_key_is_retained_without_echo(h, monkeypatch):
    secrets = {}
    monkeypatch.setattr("knowledge_world.providers.keyring.set_password", lambda service, name, value: secrets.__setitem__((service, name), value))
    body = {"base_url": "http://127.0.0.1:3000/v1/", "model": "user-model", "api_key": "synthetic-test-key", "expected_version": 0}
    response = h.request("PUT", "/providers/chat", body, status=200)
    saved = response.json()["data"]
    assert saved["base_url"] == "http://127.0.0.1:3000/v1"
    assert saved["has_secret"] and saved["enabled"] is False
    assert "synthetic-test-key" not in response.text and "secret_ref" not in response.text
    assert list(secrets.values()) == ["synthetic-test-key"]
    again = h.request("PUT", "/providers/chat", {"base_url": "https://example.com/v1", "model": "other-model", "expected_version": saved["version"]}, status=200).json()["data"]
    assert again["has_secret"] and not again["enabled"]
    assert len(secrets) == 1


@pytest.mark.parametrize("url", ["file:///tmp/model", "ftp://example.com/v1", "http://user:password@example.com/v1", "http://example.com/v1?key=secret", "https://example.com/v1#secret", "http:///v1"])
def test_provider_rejects_unsupported_or_credential_bearing_urls(h, url):
    h.request("PUT", "/providers/chat", {"base_url": url, "model": "model", "expected_version": 0}, status=400)
    assert h.scalar("SELECT count(*) FROM provider_configs") == 0
