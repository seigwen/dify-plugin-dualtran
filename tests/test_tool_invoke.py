"""Tool-invoke tests through the real Tool base class with a stub runtime."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from tools import dualtran


def make_tool(credentials: dict) -> dualtran.DualtranTool:
    tool = dualtran.DualtranTool.__new__(dualtran.DualtranTool)
    tool.runtime = SimpleNamespace(credentials=credentials)
    tool.session = SimpleNamespace()
    tool.response_type = dualtran.ToolInvokeMessage
    return tool


def patch_client(monkeypatch, handler) -> None:
    monkeypatch.setattr(
        dualtran, "_default_client", lambda timeout: httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_invoke_google_free_yields_text_then_json(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[[["Bonjour le monde", "Hello world"]]])

    patch_client(monkeypatch, handler)
    tool = make_tool({"provider": "google_free"})
    messages = list(tool._invoke({"text": "Hello world", "target_lang": "fr"}))

    assert len(messages) == 2
    text_message, json_message = messages
    assert text_message.message.text == "Bonjour le monde"
    assert json_message.message.json_object == {
        "translation": "Bonjour le monde",
        "provider": "google_free",
        "target_lang": "fr",
    }


def test_invoke_ai_engine_uses_the_credential(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "Hola"}}]})

    patch_client(monkeypatch, handler)
    tool = make_tool(
        {"provider": "openai_compatible", "api_key": "sk-x", "base_url": "", "model": "gpt-test"}
    )
    messages = list(tool._invoke({"text": "Hello", "target_lang": "es"}))

    assert messages[0].message.text == "Hola"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-x"


def test_invoke_rejects_empty_text(monkeypatch):
    patch_client(monkeypatch, lambda request: httpx.Response(200, json=[[["x", "x"]]]))
    tool = make_tool({"provider": "google_free"})
    with pytest.raises(ValueError, match="empty"):
        list(tool._invoke({"text": "  ", "target_lang": "fr"}))


def test_invoke_surfaces_provider_errors(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down")

    patch_client(monkeypatch, handler)
    tool = make_tool({"provider": "google_free"})
    with pytest.raises(RuntimeError, match="HTTP 429"):
        list(tool._invoke({"text": "Hello", "target_lang": "fr"}))
