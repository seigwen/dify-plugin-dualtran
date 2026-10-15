"""Credential validation tests — the provider's client factory is patched."""

from __future__ import annotations

import httpx
import pytest

from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from provider import dualtran as provider_module


def patch_client(monkeypatch, handler) -> None:
    monkeypatch.setattr(
        provider_module, "_http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )


def make_provider():
    # No state is needed for _validate_credentials; skip the host-provided ctor.
    return provider_module.DualtranProvider.__new__(provider_module.DualtranProvider)


def test_google_free_validates_against_the_live_endpoint_shape(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[[["hello", "hello"]]])

    patch_client(monkeypatch, handler)
    make_provider()._validate_credentials({"provider": "google_free"})
    assert "translate.googleapis.com" in seen["url"]


def test_google_free_non_200_raises(monkeypatch):
    patch_client(monkeypatch, lambda request: httpx.Response(503))
    with pytest.raises(ToolProviderCredentialValidationError, match="HTTP 503"):
        make_provider()._validate_credentials({"provider": "google_free"})


def test_openai_compatible_requires_a_key(monkeypatch):
    patch_client(monkeypatch, lambda request: httpx.Response(200))
    with pytest.raises(ToolProviderCredentialValidationError, match="needs an API key"):
        make_provider()._validate_credentials({"provider": "openai_compatible", "api_key": ""})


def test_openai_compatible_checks_models_endpoint(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": []})

    patch_client(monkeypatch, handler)
    make_provider()._validate_credentials(
        {"provider": "openai_compatible", "api_key": "k", "base_url": "https://proxy.example/v1"}
    )
    assert seen["url"] == "https://proxy.example/v1/models"
    assert seen["auth"] == "Bearer k"


def test_openai_compatible_rejection_raises(monkeypatch):
    patch_client(monkeypatch, lambda request: httpx.Response(401))
    with pytest.raises(ToolProviderCredentialValidationError, match="HTTP 401"):
        make_provider()._validate_credentials({"provider": "openai_compatible", "api_key": "bad"})


def test_deepl_uses_the_free_usage_endpoint_for_fx_keys(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        return httpx.Response(200, json={"character_count": 1})

    patch_client(monkeypatch, handler)
    make_provider()._validate_credentials({"provider": "deepl", "api_key": "abc:fx"})
    assert seen["host"] == "api-free.deepl.com"


def test_unknown_engine_raises(monkeypatch):
    patch_client(monkeypatch, lambda request: httpx.Response(200))
    with pytest.raises(ToolProviderCredentialValidationError, match="Unknown engine"):
        make_provider()._validate_credentials({"provider": "yandex"})
