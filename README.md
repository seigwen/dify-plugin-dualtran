# DualTran for Dify

Translate text in any Dify workflow with **Google** (free, no account) or
**your own AI model** (BYOK). A tool plugin for
[Dify](https://dify.ai), from the makers of the
[DualTran browser extension](https://github.com/seigwen/DualTran-extension).

## Engines

| Engine | Key needed | Notes |
|---|---|---|
| **Google (free)** | No | Uses the public `translate.googleapis.com` gtx endpoint — the same one the DualTran browser extension uses for its Google engine. |
| **AI — OpenAI-compatible** | Yes (BYOK) | Any `/chat/completions` endpoint: OpenAI, DeepSeek, Groq, Mistral, OpenRouter, local servers (Ollama, LM Studio), … Set the base URL + model. |
| **DeepL** | Yes (BYOK) | Free keys (ending in `:fx`) use `api-free.deepl.com`, paid keys `api.deepl.com`. |

Configure the engine once in the plugin's authorization card; the key fields
are only needed for the AI / DeepL engines.

## Tool: DualTran Translate

| Parameter | Required | Notes |
|---|---|---|
| `text` | yes | The text to translate (supports Dify variables). |
| `target_lang` | yes | Language picker (44 languages, default `en`). Stores the language code: `en`, `zh-CN`, `ja`, … |
| `source_lang` | no | Language code or `auto` (detect). |
| `reasoning` | no | Reasoning-effort override for this step: `lowest` (default), `default`, `none`, `minimal`, `low`, `medium`, `high`. Overrides the plugin credential. |

Outputs: a **text** message (the translation) and a **JSON** message:
`{ "translation": "...", "provider": "...", "target_lang": "...", "reasoning": "..." }`,
where `reasoning` is the effort actually sent (`""` when the request carries none).

### Model picker

The `model` credential is a static curated list plus **Custom…**: Dify
credentials cannot fetch a live catalogue, so the list is fixed. Values are
`openai_compatible/<model id>`; the prefix is the engine, the rest is the model
id. Anything not on the list is reachable by picking Custom… (or typing a bare
id), and the base URL stays editable for proxies and self-hosted servers.

## Parity with the DualTran browser extension (plan 64 D2-A)

This plugin is a thin Python implementation — it does **not** embed the JS
core. Differences:

| Aspect | Browser extension / JS core | This Dify plugin |
|---|---|---|
| Google engine | gtx endpoint, batching, TWP-compatible parsing | Same endpoint & parsing semantics; one text per call |
| AI engine | TWP prompt pipeline (context-aware, word-dictionary mode) | Compact translation system prompt |
| Providers | 20+ via AI SDK (OpenAI, Anthropic, Gemini, …) | Any OpenAI-compatible endpoint + DeepL |
| Caching | Session + optional file cache | None (stateless) |

## Development

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt pytest
.venv/bin/python -m pytest tests/          # 22 unit tests (httpx MockTransport)
bash scripts/verify.sh                     # tests + package + artifact assertions
```

## License

The plugin source is MIT; it calls third-party translation services with the
user's own credentials. See PRIVACY.md.

## Languages

The engine itself has no interface: strings this package exposes are MCP tool
names/descriptions and parameter docs, which LLM clients and protocol tooling
consume in English. Localising them would hurt discoverability, so they stay
English by policy. Any future user-facing surface must follow the DualTran i18n
standard (38 catalogues, `locales/<code>/messages.json`).
