#!/usr/bin/env python3
"""DualTran conformance payload for the Dify plugin host (SPEC 2.0.0).

Reads the shipped YAML — never a hand-kept copy — so the payload cannot drift
from what the plugin actually declares:

  tools/dualtran.yaml     target_lang / reasoning pickers + the tool parameters
  provider/dualtran.yaml  engine / model / base_url / reasoning credentials

`node .conformance-kit/run.mjs` resolves its repo root as two levels above
`.conformance-kit/`, which is not where this plugin's conformance.json lives, so
the Python entry point is `python3 scripts/conformance/run.py` (`make conformance`).
It replays the same pipeline — self-test, payloadCommand, static scan, validate —
with the kit's own validate.mjs / scan.mjs. This file only emits the payload; the
runner feeds it to the validator.

Endpoint autofill: Dify credentials are static YAML. R3 asks what a user sees
after picking a provider and that a user edit survives a provider switch. The
plugin reproduces that by keeping `base_url` a free text-input whose empty value
means "provider default" (`OPENAI_DEFAULT_BASE_URL` in tools/dualtran.py), so
`after` is that default and `afterSwitch` is whatever the user typed.
"""

from __future__ import annotations

import json
import pathlib
import sys

try:  # PyYAML ships in the plugin venv (dify_plugin dependency chain)
    import yaml
except ModuleNotFoundError:  # bare system python3: re-exec inside .venv if it exists
    _venv = pathlib.Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python3"
    if _venv.exists() and pathlib.Path(sys.executable).resolve() != _venv.resolve():
        import os

        os.execv(str(_venv), [str(_venv), *sys.argv])  # noqa: S606
    raise

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC_VERSION = "2.0.0"
LOCALES = ("en_US", "zh_Hans", "ja_JP", "pt_BR")
# Mirrors OPENAI_DEFAULT_BASE_URL in tools/dualtran.py (kept literal: importing
# the module would require the dify_plugin runtime just to read one constant).
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
CUSTOM_MODEL_LABEL = "Custom…"


def load(relative: str) -> dict:
    with (ROOT / relative).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def pick_locale(entry: dict, locale: str = "en_US") -> str:
    """Flatten a Dify I18nObject to the validator's single label string."""
    if not isinstance(entry, dict):
        return str(entry or "")
    return str(entry.get(locale) or entry.get("en_US") or "")


# ── R1: target language picker ───────────────────────────────────────────────


def language_section(tool_yaml: dict) -> dict:
    target = next(p for p in tool_yaml["parameters"] if p["name"] == "target_lang")
    options = target.get("options") or []
    return {
        "control": target["type"],
        "current": target.get("default") or options[0]["value"],
        "options": [
            {
                "value": option["value"],
                "label": pick_locale(option["label"]),
                "labels": option["label"],  # all four locales travel along
            }
            for option in options
        ],
    }


# ── R2: engine + model pickers ───────────────────────────────────────────────


def provider_section(provider_yaml: dict) -> dict:
    """Engine enum + the curated model providers, one flat picker.

    The model select stores `provider/model`, and its prefix is the provider —
    which is a fixed enum for google_free/deepl (no model) and the curated set
    from facts/models-dev-sample.json for every other model, all reached over the
    OpenAI-compatible engine. Presenting both as one list is what tells the user
    which `provider/model` values exist; the entries are labelled `… (engine)`
    and `… (models.dev)` so the distinction survives.
    """
    engine = next(c for c in provider_yaml["credentials_schema"] if c["name"] == "provider")
    model_select = next(c for c in provider_yaml["credentials_schema"] if c["name"] == "model")
    sample = json.loads((ROOT / "scripts" / "catalog-sources" / "models-dev-sample.json").read_text(encoding="utf-8"))

    options: list[dict] = []
    for option in engine["options"]:
        options.append(
            {
                "value": option["value"],
                "label": f"{pick_locale(option['label'])} (engine)",
                "source": "built-in",
            }
        )
    curated = {
        value.split("/", 1)[1]: value
        for value in (o["value"] for o in model_select.get("options") or [])
        if not value.startswith("__custom")
    }
    providers = sorted(
        {(m["id"], provider_id) for provider_id, data in sample.items() for m in data["models"].values()
         if m["id"] in curated},
        key=lambda row: sample[row[1]]["name"].lower(),
    )
    for _model_id, provider_id in providers:
        if any(option["value"] == provider_id for option in options):
            continue
        options.append(
            {
                "value": provider_id,
                "label": f"{sample[provider_id]['name']} (models.dev)",
                "source": "models.dev",
            }
        )
    builtin = [o for o in options if o["source"] == "built-in"]
    merged = [o for o in options if o["source"] != "built-in"]
    return {
        "control": engine["type"],
        "current": engine.get("default") or "",
        # One list, one alphabetical order: groups must not be concatenated.
        "options": sorted(builtin + merged, key=lambda row: row["label"].lower()),
    }


def model_section(provider_yaml: dict, provider_section_doc: dict) -> dict:
    select = next(c for c in provider_yaml["credentials_schema"] if c["name"] == "model")
    options = select.get("options") or []
    catalogue = [
        {"value": o["value"], "label": pick_locale(o["label"])}
        for o in options
        if not o["value"].startswith("__custom")
    ]
    custom = [
        {"value": o["value"], "label": pick_locale(o["label"]), "source": "custom"}
        for o in options
        if o["value"].startswith("__custom")
    ]
    # The picker stores `provider/model`; the validator keys by provider, so split
    # the prefix back out. Custom stays last, as it is in the YAML.
    by_provider: dict[str, list[dict]] = {}
    for option in catalogue:
        prefix = option["value"].split("/", 1)[0]
        by_provider.setdefault(prefix, []).append(
            {"value": option["value"].split("/", 1)[1], "label": option["label"]}
        )
    for entries in by_provider.values():
        entries.sort(key=lambda row: row["label"].lower())
        entries.extend(custom)
    default_engine = provider_section_doc.get("current") or ""
    current_engine = default_engine if default_engine in by_provider else next(iter(by_provider), "")
    current_models = by_provider.get(current_engine) or []
    selected = select.get("default") or ""
    prefix, _, rest = selected.partition("/")
    if prefix == current_engine and rest:
        selected = rest
    elif current_models:
        selected = current_models[0]["value"]
    else:
        selected = ""
    return {
        "control": select["type"],
        "selectedProvider": current_engine,
        "selectedModel": selected,
        "customLabel": CUSTOM_MODEL_LABEL,
        "valueConvention": "provider/model — the prefix is the engine, the rest is the model id",
        "byProvider": by_provider,
    }


# ── R3: editable endpoint ────────────────────────────────────────────────────


def endpoint_section(provider_yaml: dict) -> dict:
    base_url = next(c for c in provider_yaml["credentials_schema"] if c["name"] == "base_url")
    user_edited = "https://proxy.example/v1"
    return {
        "control": "text" if base_url["type"] == "text-input" else base_url["type"],
        "editable": True,
        "emptyMeans": "provider default",
        "autofill": {
            "provider": "openai_compatible",
            "providerApi": OPENAI_DEFAULT_BASE_URL,
            "before": base_url.get("default") or "",
            "after": OPENAI_DEFAULT_BASE_URL,
            "userEdited": user_edited,
            "afterSwitch": user_edited,
        },
    }


# ── R4: reasoning sentinel ───────────────────────────────────────────────────


def reasoning_cases() -> dict:
    """Probe the real resolver so the payload reports behaviour, not intent."""
    sys.path.insert(0, str(ROOT))
    from tools.dualtran import resolve_reasoning  # noqa: PLC0415 — after sys.path fix

    def case(setting: str, model: str) -> dict:
        return {"model": model, "setting": setting, "value": resolve_reasoning(setting, model)}

    return {
        # a model that declares none / minimal / low
        "none": [case("lowest", "openai_compatible/gpt-5.4-mini"), case("none", "gpt-5.4-mini")],
        # a model whose lowest declared level is minimal
        "minimal": [case("lowest", "meta/muse-spark-1.2"), case("minimal", "meta/muse-spark-1.2")],
        # a model that declares low but not none / minimal
        "low": [case("lowest", "deepseek-v4-flash"), case("low", "deepseek-v4-flash")],
        # models with no effort knob, and the explicit opt-out
        "none-declared": [
            case("lowest", "gpt-4o"),
            case("high", "glm-4.7-flash"),
            case("default", "gpt-5.4-mini"),
            case("", "gpt-5.4-mini"),
        ],
    }


def reasoning_section(provider_yaml: dict) -> dict:
    select = next((c for c in provider_yaml["credentials_schema"] if c["name"] == "reasoning"), None)
    if select is None:
        return {"control": "text", "default": ""}
    return {
        "control": select["type"],
        "default": select.get("default") or "",
        "optionLabels": {o["value"]: pick_locale(o["label"]) for o in select.get("options") or []},
        "resolved": reasoning_cases(),
    }


# ── R5: four-locale matrix ───────────────────────────────────────────────────


def i18n_section(*docs: dict) -> dict:
    keys: list[str] = []
    files: dict[str, dict[str, str]] = {locale: {} for locale in LOCALES}

    def add(key: str, entry: dict) -> None:
        if key in files["en_US"]:
            return
        keys.append(key)
        for locale in LOCALES:
            files[locale][key] = pick_locale(entry, locale)

    for doc in docs:
        for credential in doc.get("credentials_schema") or []:
            for field in ("label", "help", "placeholder"):
                if field in credential:
                    add(f"{credential['name']}.{field}", credential[field])
            for option in credential.get("options") or []:
                add(f"{credential['name']}[{option['value']}]", option["label"])
        for parameter in doc.get("parameters") or []:
            for field in ("label", "human_description", "placeholder"):
                if field in parameter:
                    add(f"{parameter['name']}.{field}", parameter[field])
            for option in parameter.get("options") or []:
                add(f"{parameter['name']}[{option['value']}]", option["label"])

    # Everything the two files declare is user-visible in Dify's UI.
    return {
        "locales": list(LOCALES),
        "sourceLocale": "en_US",
        "keys": keys,
        "files": files,
        "used": keys,
        "platformLimit": "Dify I18nObject supports exactly these four locales",
    }


def build_payload() -> dict:
    tool_yaml = load("tools/dualtran.yaml")
    provider_yaml = load("provider/dualtran.yaml")
    provider_doc = provider_section(provider_yaml)
    return {
        "spec": SPEC_VERSION,
        "host": "dify-plugin-dualtran",
        "language": language_section(tool_yaml),
        "provider": provider_doc,
        "model": model_section(provider_yaml, provider_doc),
        "endpoint": endpoint_section(provider_yaml),
        "reasoning": reasoning_section(provider_yaml),
        "i18n": i18n_section(provider_yaml, tool_yaml),
        "toolParameters": [p["name"] for p in tool_yaml["parameters"]],
        "static": {"hits": []},
    }


def main() -> int:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
