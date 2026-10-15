"""Pure translation-engine tests — httpx MockTransport, no network."""

from __future__ import annotations

import json

import httpx
import pytest

from tools import dualtran


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_google_response_matches_core_semantics():
    payload = [[["Bonjour le monde", "Hello world", None, None, 10]], None, "en"]
    assert dualtran.parse_google_response(payload) == "Bonjour le monde"
    assert dualtran.parse_google_response([[["a"], ["b"]]]) == "ab"
    assert dualtran.parse_google_response(None) == ""
    assert dualtran.parse_google_response("junk") == ""
    assert dualtran.parse_google_response([]) == ""


def test_translate_google_free_builds_the_gtx_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[[["Bonjour le monde", "Hello world", None, None, 10]], None, "en"])

    out = dualtran.translate_google_free("Hello world", "fr", "en", client=mock_client(handler))
    assert out == "Bonjour le monde"
    url = seen["url"]
    assert "translate.googleapis.com/translate_a/single" in url
    for fragment in ("client=gtx", "sl=en", "tl=fr", "dt=t", "q=Hello+world"):
        assert fragment in url, fragment


def test_google_non_200_surfaces_a_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down")

    with pytest.raises(RuntimeError, match=r"Google translation failed: HTTP 429 \(rate limit exceeded\)"):
        dualtran.translate_google_free("x", "fr", "auto", client=mock_client(handler))


def test_google_empty_translation_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[[[None, None]]])

    with pytest.raises(RuntimeError, match="empty response"):
        dualtran.translate_google_free("x", "fr", "auto", client=mock_client(handler))


def test_openai_compatible_posts_chat_completions():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "  Hola mundo  "}}]})

    out = dualtran.translate_openai_compatible(
        "Hello world", "es", "key-1", "https://proxy.example/v1", "model-1", client=mock_client(handler)
    )
    assert out == "Hola mundo"
    assert captured["url"] == "https://proxy.example/v1/chat/completions"
    assert captured["auth"] == "Bearer key-1"
    assert captured["body"]["model"] == "model-1"
    assert captured["body"]["messages"][1]["content"] == "Hello world"
    assert "es" in captured["body"]["messages"][0]["content"]


def test_openai_compatible_defaults_to_the_openai_endpoint():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    dualtran.translate_openai_compatible("x", "en", "k", "", "m", client=mock_client(handler))
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"


def test_openai_compatible_requires_key_and_model():
    with pytest.raises(RuntimeError, match="needs an API key"):
        dualtran.translate_openai_compatible("x", "en", "", "", "m")
    with pytest.raises(RuntimeError, match="needs a model name"):
        dualtran.translate_openai_compatible("x", "en", "k", "", "")


def test_openai_compatible_401_maps_to_invalid_key_hint():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    with pytest.raises(RuntimeError, match=r"AI translation failed: HTTP 401 \(invalid API key\)"):
        dualtran.translate_openai_compatible("x", "en", "k", "", "m", client=mock_client(handler))


def test_deepl_free_key_uses_the_free_endpoint_and_uppercases_the_target():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["host"] = request.url.host
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"translations": [{"text": "Hallo Welt"}]})

    out = dualtran.translate_deepl("Hello world", "de-DE", "abc:fx", client=mock_client(handler))
    assert out == "Hallo Welt"
    assert captured["host"] == "api-free.deepl.com"
    assert captured["auth"] == "DeepL-Auth-Key abc:fx"
    assert "target_lang=DE" in captured["body"]


def test_deepl_paid_key_uses_the_paid_endpoint():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["host"] = request.url.host
        return httpx.Response(200, json={"translations": [{"text": "Hallo"}]})

    dualtran.translate_deepl("Hello", "de", "paid-key", client=mock_client(handler))
    assert captured["host"] == "api.deepl.com"


def test_translate_text_validates_and_dispatches():
    with pytest.raises(ValueError, match="empty"):
        dualtran.translate_text(provider="google_free", text="   ", target_lang="fr")
    with pytest.raises(ValueError, match="required"):
        dualtran.translate_text(provider="google_free", text="x", target_lang="")
    with pytest.raises(ValueError, match="Unknown engine"):
        dualtran.translate_text(provider="yandex", text="x", target_lang="fr")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[[["Bonjour", "Hello"]]])

    assert (
        dualtran.translate_text(
            provider="google_free", text="Hello", target_lang="fr", client=mock_client(handler)
        )
        == "Bonjour"
    )
