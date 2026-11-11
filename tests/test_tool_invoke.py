"""Tool-invoke tests through the real Tool base class with a stub runtime."""

from __future__ import annotations

import json
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
        # no model on this engine, so nothing is sent as reasoning_effort
        "reasoning": "",
    }


def test_invoke_ai_engine_uses_the_credential(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Hola"}}]})

    patch_client(monkeypatch, handler)
    tool = make_tool(
        {"provider": "openai_compatible", "api_key": "sk-x", "base_url": "", "model": "gpt-test"}
    )
    messages = list(tool._invoke({"text": "Hello", "target_lang": "es"}))

    assert messages[0].message.text == "Hola"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-x"


def test_invoke_passes_the_credential_reasoning_to_the_request(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Hola"}}]})

    patch_client(monkeypatch, handler)
    tool = make_tool(
        {
            "provider": "openai_compatible",
            "api_key": "sk-x",
            "model": "openai_compatible/deepseek-v4-flash",
            "reasoning": "lowest",
        }
    )
    messages = list(tool._invoke({"text": "Hello", "target_lang": "es"}))

    assert captured["body"]["reasoning_effort"] == "low"  # none/minimal undeclared
    assert captured["body"]["model"] == "deepseek-v4-flash"  # engine prefix stripped
    assert messages[1].message.json_object["reasoning"] == "low"


def test_invoke_tool_reasoning_overrides_the_credential(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Hola"}}]})

    patch_client(monkeypatch, handler)
    tool = make_tool(
        {
            "provider": "openai_compatible",
            "api_key": "sk-x",
            "model": "openai_compatible/gpt-5.4-mini",
            "reasoning": "lowest",
        }
    )
    list(tool._invoke({"text": "Hello", "target_lang": "es", "reasoning": "high"}))

    assert captured["body"]["reasoning_effort"] == "high"


def test_invoke_omits_reasoning_effort_for_default(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Hola"}}]})

    patch_client(monkeypatch, handler)
    tool = make_tool(
        {
            "provider": "openai_compatible",
            "api_key": "sk-x",
            "model": "openai_compatible/gpt-5.4-mini",
            "reasoning": "default",
        }
    )
    messages = list(tool._invoke({"text": "Hello", "target_lang": "es"}))

    assert "reasoning_effort" not in captured["body"]
    assert messages[1].message.json_object["reasoning"] == ""


def test_resolve_reasoning_lowest_walks_none_then_minimal_then_low():
    assert dualtran.resolve_reasoning("lowest", "gpt-5.4-mini") == "none"
    assert dualtran.resolve_reasoning("lowest", "meta/muse-spark-1.2") == "minimal"
    assert dualtran.resolve_reasoning("lowest", "deepseek-v4-flash") == "low"
    assert dualtran.resolve_reasoning("lowest", "some-unlisted-model") == "none"


def test_resolve_reasoning_omits_for_default_empty_and_stateless_models():
    assert dualtran.resolve_reasoning("", "gpt-5.4-mini") == ""
    assert dualtran.resolve_reasoning("default", "gpt-5.4-mini") == ""
    assert dualtran.resolve_reasoning("high", "gpt-4o") == ""
    assert dualtran.resolve_reasoning("nonsense", "gpt-5.4-mini") == ""


def test_resolve_reasoning_clamps_down_to_the_model_table():
    assert dualtran.resolve_reasoning("high", "deepseek-v4-flash") == "high"
    assert dualtran.resolve_reasoning("medium", "deepseek-v4-flash") == "low"
    assert dualtran.resolve_reasoning("minimal", "deepseek-v4-flash") == "low"
    assert dualtran.resolve_reasoning("high", "meta/muse-spark-1.2") == "high"


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
