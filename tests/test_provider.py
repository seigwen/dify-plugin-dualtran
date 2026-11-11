"""Credential validation tests — the provider's client factory is patched."""

from __future__ import annotations

import json

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


def test_openai_compatible_requires_a_model(monkeypatch):
    patch_client(monkeypatch, lambda request: httpx.Response(200))
    with pytest.raises(ToolProviderCredentialValidationError, match="needs a model"):
        make_provider()._validate_credentials(
            {"provider": "openai_compatible", "api_key": "k", "model": ""}
        )


def test_openai_compatible_probes_the_chat_endpoint_with_reasoning(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    patch_client(monkeypatch, handler)
    make_provider()._validate_credentials(
        {
            "provider": "openai_compatible",
            "api_key": "k",
            "base_url": "https://proxy.example/v1",
            "model": "openai_compatible/gpt-5.4-mini",
            "reasoning": "lowest",
        }
    )
    assert seen["url"] == "https://proxy.example/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "gpt-5.4-mini"
    assert seen["body"]["reasoning_effort"] == "none"


def test_openai_compatible_omits_reasoning_for_default(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    patch_client(monkeypatch, handler)
    make_provider()._validate_credentials(
        {
            "provider": "openai_compatible",
            "api_key": "k",
            "model": "openai_compatible/gpt-5.4-mini",
            "reasoning": "default",
        }
    )
    assert "reasoning_effort" not in seen["body"]


def test_openai_compatible_rejection_raises(monkeypatch):
    patch_client(monkeypatch, lambda request: httpx.Response(401, text="bad key"))
    with pytest.raises(ToolProviderCredentialValidationError, match="HTTP 401"):
        make_provider()._validate_credentials(
            {"provider": "openai_compatible", "api_key": "bad", "model": "openai_compatible/gpt-4o"}
        )


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
