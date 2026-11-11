"""
DualTran translate tool for Dify (plan 64 C, decision D2-A).

Thin Python implementation over three engines:
  - google_free        translate.googleapis.com gtx endpoint (the same URL and
                       response shape the JS core uses — parse semantics mirror
                       @dualtran/core parseGoogleResponse)
  - openai_compatible  any OpenAI-compatible /chat/completions endpoint (BYOK)
  - deepl              api-free.deepl.com / api.deepl.com (BYOK)

Parity note: this is intentionally not the JS core — the README carries the
parity table (Google engine is feature-parity; the AI engine uses a compact
prompt instead of the extension's TWP prompt pipeline).
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import httpx

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

GOOGLE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
DEEPL_FREE_ENDPOINT = "https://api-free.deepl.com/v2/translate"
DEEPL_PAID_ENDPOINT = "https://api.deepl.com/v2/translate"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"

AI_SYSTEM_PROMPT = (
    "You are a professional translator. Translate the text the user sends into "
    "{target_language}. Output ONLY the translation, without explanations, "
    "quotes or extra formatting. Preserve the original formatting and line "
    "breaks."
)

# ── Reasoning effort (R4) ─────────────────────────────────────────────────────
# The picker offers one superset; each catalogue model declares its own levels.
# A selection outside a model's table is clamped *downwards* (cheaper first) so a
# typo can never escalate cost, and `lowest` walks none → minimal → low.
REASONING_LEVELS = ("lowest", "default", "none", "minimal", "low", "medium", "high")
LOWEST_ORDER = ("none", "minimal", "low")

# model id → effort values the provider accepts (mirrors facts/models-dev-sample.json)
REASONING_TABLE: dict[str, tuple[str, ...]] = {
    "gpt-4o": (),
    "gpt-5.4-mini": ("none", "low", "medium", "high", "xhigh"),
    "gpt-5.6": ("none", "low", "medium", "high", "xhigh", "max"),
    "deepseek-v4-flash": ("low", "high", "max"),
    "deepseek-v4-pro": ("low", "high", "max"),
    "kimi-k3": ("low", "high", "max"),
    "glm-4.7-flash": (),
    "qwen3.7-plus": (),
    "mistral-small-latest": (),
    "meta/muse-spark-1.2": ("minimal", "low", "medium", "high", "xhigh"),
}
_DEFAULT_TABLE = LOWEST_ORDER


def reasoning_table(model: str) -> tuple[str, ...]:
    """Levels declared for a model; unknown models get the safest three."""
    key = model_id(model) if model else ""
    return REASONING_TABLE.get(key, _DEFAULT_TABLE)


def resolve_reasoning(setting: str, model: str = "") -> str:
    """Map a picker value to the `reasoning_effort` to send ("" = omit).

    - "" / "default"     → omit the field entirely
    - "lowest"           → none → minimal → low, first the model declares
    - anything else      → itself, capped down to the nearest declared level
    - model declares no effort values → omit (it has no reasoning knob)
    """
    value = (setting or "").strip().lower()
    if value in ("", "default"):
        return ""
    table = reasoning_table(model)
    if not table:
        return ""
    if value == "lowest":
        for level in LOWEST_ORDER:
            if level in table:
                return level
        return ""
    if value not in REASONING_LEVELS:
        return ""
    if value in table:
        return value
    # Clamp down: the highest declared level strictly below the request.
    ordered = [level for level in REASONING_LEVELS if level in table]
    lower = [level for level in ordered if REASONING_LEVELS.index(level) < REASONING_LEVELS.index(value)]
    return lower[-1] if lower else (ordered[0] if ordered else "")


def _default_client(timeout: float) -> httpx.Client:
    """Overridable in tests (monkeypatch to inject a MockTransport client)."""
    return httpx.Client(timeout=timeout)


_HTTP_ERROR_HINTS = {
    401: "invalid API key",
    403: "access denied",
    429: "rate limit exceeded",
    500: "provider server error",
    503: "provider unavailable",
}


def parse_google_response(payload: Any) -> str:
    """Mirror @dualtran/core parseGoogleResponse: join response[0][i][0]."""
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        return ""
    parts: list[str] = []
    for segment in payload[0]:
        if isinstance(segment, list) and segment and segment[0]:
            parts.append(segment[0])
    return "".join(parts)


def _http_error(engine: str, response: httpx.Response) -> RuntimeError:
    hint = _HTTP_ERROR_HINTS.get(response.status_code)
    detail = f"{response.status_code}"
    if hint:
        detail += f" ({hint})"
    body = ""
    try:
        body = response.text[:200]
    except Exception:  # pragma: no cover - defensive
        pass
    suffix = f" — {body}" if body else ""
    return RuntimeError(f"{engine} translation failed: HTTP {detail}{suffix}")


def translate_google_free(
    text: str,
    target_lang: str,
    source_lang: str = "auto",
    client: httpx.Client | None = None,
) -> str:
    owns_client = client is None
    http = client or _default_client(30.0)
    try:
        response = http.get(
            GOOGLE_ENDPOINT,
            params={
                "client": "gtx",
                "sl": source_lang or "auto",
                "tl": target_lang,
                "dt": "t",
                "q": text,
            },
        )
    finally:
        if owns_client:
            http.close()
    if response.status_code != 200:
        raise _http_error("Google", response)
    translated = parse_google_response(response.json())
    if not translated:
        raise RuntimeError("Google translation failed: empty response")
    return translated


def model_id(option: str) -> str:
    """Strip the picker's `engine/` prefix: the model select stores `provider/model`."""
    value = (option or "").strip()
    if value.startswith("__custom"):
        return ""
    engine, sep, rest = value.partition("/")
    return rest if sep and engine == "openai_compatible" else value


def translate_openai_compatible(
    text: str,
    target_lang: str,
    api_key: str,
    base_url: str = "",
    model: str = "",
    reasoning: str = "",
    client: httpx.Client | None = None,
) -> str:
    if not api_key:
        raise RuntimeError("The OpenAI-compatible engine needs an API key (BYOK).")
    model = model_id(model)
    if not model:
        raise RuntimeError("The OpenAI-compatible engine needs a model name.")
    base = (base_url or OPENAI_DEFAULT_BASE_URL).rstrip("/")
    body: dict[str, Any] = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT.format(target_language=target_lang)},
            {"role": "user", "content": text},
        ],
    }
    effort = resolve_reasoning(reasoning, model)
    if effort:
        body["reasoning_effort"] = effort
    owns_client = client is None
    http = client or _default_client(60.0)
    try:
        response = http.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
    finally:
        if owns_client:
            http.close()
    if response.status_code != 200:
        raise _http_error("AI", response)
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"AI translation failed: unexpected response shape ({exc})") from exc
    translated = (content or "").strip()
    if not translated:
        raise RuntimeError("AI translation failed: empty response")
    return translated


def translate_deepl(
    text: str,
    target_lang: str,
    api_key: str,
    client: httpx.Client | None = None,
) -> str:
    if not api_key:
        raise RuntimeError("The DeepL engine needs an API key (BYOK).")
    endpoint = DEEPL_FREE_ENDPOINT if api_key.strip().endswith(":fx") else DEEPL_PAID_ENDPOINT
    owns_client = client is None
    http = client or _default_client(30.0)
    try:
        response = http.post(
            endpoint,
            headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
            data={"text": text, "target_lang": target_lang.upper().split("-")[0]},
        )
    finally:
        if owns_client:
            http.close()
    if response.status_code != 200:
        raise _http_error("DeepL", response)
    try:
        translated = response.json()["translations"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"DeepL translation failed: unexpected response shape ({exc})") from exc
    if not translated:
        raise RuntimeError("DeepL translation failed: empty response")
    return translated


def translate_text(
    *,
    provider: str,
    text: str,
    target_lang: str,
    source_lang: str = "auto",
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    reasoning: str = "",
    client: httpx.Client | None = None,
) -> str:
    """Validate the parameters, dispatch to the selected engine, return the translation."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Nothing to translate: the text is empty.")
    if not (target_lang or "").strip():
        raise ValueError("target_lang is required.")
    if provider == "google_free":
        return translate_google_free(text, target_lang, source_lang, client=client)
    if provider == "openai_compatible":
        return translate_openai_compatible(
            text, target_lang, api_key, base_url, model, reasoning, client=client
        )
    if provider == "deepl":
        return translate_deepl(text, target_lang, api_key, client=client)
    raise ValueError(f"Unknown engine '{provider}'.")


class DualtranTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        credentials: dict[str, Any] = getattr(self.runtime, "credentials", None) or {}
        provider = credentials.get("provider") or "google_free"
        target_lang = tool_parameters.get("target_lang") or "en"
        # The per-step parameter wins; the credential is the default for the provider.
        reasoning = tool_parameters.get("reasoning") or credentials.get("reasoning") or ""
        translated = translate_text(
            provider=provider,
            text=tool_parameters.get("text", ""),
            target_lang=target_lang,
            source_lang=tool_parameters.get("source_lang") or "auto",
            api_key=credentials.get("api_key") or "",
            base_url=credentials.get("base_url") or "",
            model=credentials.get("model") or "",
            reasoning=reasoning,
        )
        yield self.create_text_message(translated)
        yield self.create_json_message(
            {
                "translation": translated,
                "provider": provider,
                "target_lang": target_lang,
                "reasoning": resolve_reasoning(reasoning, credentials.get("model") or ""),
            }
        )
