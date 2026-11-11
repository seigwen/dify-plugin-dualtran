from __future__ import annotations

from typing import Any

import httpx

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from tools.dualtran import translate_openai_compatible

GOOGLE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
DEEPL_FREE_USAGE_ENDPOINT = "https://api-free.deepl.com/v2/usage"
DEEPL_PAID_USAGE_ENDPOINT = "https://api.deepl.com/v2/usage"


def _http_client() -> httpx.Client:
    """Overridable in tests (monkeypatch this to inject a MockTransport client)."""
    return httpx.Client(timeout=15.0)


class DualtranProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        provider = (credentials.get("provider") or "google_free").strip()
        api_key = (credentials.get("api_key") or "").strip()
        base_url = (credentials.get("base_url") or "").strip()
        model = (credentials.get("model") or "").strip()
        reasoning = (credentials.get("reasoning") or "lowest").strip()
        try:
            with _http_client() as client:
                if provider == "google_free":
                    response = client.get(
                        GOOGLE_ENDPOINT,
                        params={"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": "hello"},
                    )
                    if response.status_code != 200:
                        raise RuntimeError(f"Google endpoint returned HTTP {response.status_code}.")
                elif provider == "openai_compatible":
                    if not api_key:
                        raise RuntimeError("The OpenAI-compatible engine needs an API key.")
                    if not model:
                        raise RuntimeError("The OpenAI-compatible engine needs a model.")
                    # A real translation round-trip: proves the key, the endpoint
                    # and the reasoning level are all accepted by the provider.
                    translate_openai_compatible(
                        "hello", "en", api_key, base_url, model, reasoning, client=client
                    )
                elif provider == "deepl":
                    if not api_key:
                        raise RuntimeError("The DeepL engine needs an API key.")
                    endpoint = (
                        DEEPL_FREE_USAGE_ENDPOINT if api_key.endswith(":fx") else DEEPL_PAID_USAGE_ENDPOINT
                    )
                    response = client.get(
                        endpoint, headers={"Authorization": f"DeepL-Auth-Key {api_key}"}
                    )
                    if response.status_code != 200:
                        raise RuntimeError(
                            f"DeepL rejected the credentials (HTTP {response.status_code})."
                        )
                else:
                    raise RuntimeError(f"Unknown engine '{provider}'.")
        except Exception as e:  # noqa: BLE001 — the platform expects a validation error here
            raise ToolProviderCredentialValidationError(str(e)) from e
