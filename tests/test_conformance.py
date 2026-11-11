"""Conformance tests for the Dify settings surface (R1–R5).

These read the real YAML the plugin ships, so they fail until the pickers, the
reasoning sentinel and the four-locale labels are in place.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCALES = ("en_US", "zh_Hans", "ja_JP", "pt_BR")
# Dify renders select options in declaration order; labels stay un-prefixed here
# so both the YAML and the sorted payload can be checked consistently.
REASONING_LEVELS = ["lowest", "default", "none", "minimal", "low", "medium", "high"]
MIN_LANGUAGES = 38
# Engines whose request carries no model parameter.
MODEL_LESS_ENGINES = {"google_free", "deepl"}


def load(relative: str) -> dict:
    with (ROOT / relative).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture(scope="module")
def tool_yaml() -> dict:
    return load("tools/dualtran.yaml")


@pytest.fixture(scope="module")
def provider_yaml() -> dict:
    return load("provider/dualtran.yaml")


def param(doc: dict, name: str) -> dict:
    for entry in doc["parameters"]:
        if entry["name"] == name:
            return entry
    raise AssertionError(f"parameter {name!r} is missing")


def credential(doc: dict, name: str) -> dict:
    for entry in doc["credentials_schema"]:
        if entry["name"] == name:
            return entry
    raise AssertionError(f"credential {name!r} is missing")


# ── R1: target language picker ───────────────────────────────────────────────


def test_target_lang_is_a_select(tool_yaml):
    target = param(tool_yaml, "target_lang")
    assert target["type"] == "select"
    assert target["required"] is True


def test_target_lang_has_at_least_38_options(tool_yaml):
    options = param(tool_yaml, "target_lang")["options"]
    assert len(options) >= MIN_LANGUAGES
    values = [option["value"] for option in options]
    assert len(values) == len(set(values))
    assert "" not in values
    assert "auto" not in values


def test_target_lang_options_carry_readable_four_locale_labels(tool_yaml):
    for option in param(tool_yaml, "target_lang")["options"]:
        label = option["label"]
        assert set(label) == set(LOCALES), option["value"]
        for locale in LOCALES:
            assert label[locale].strip(), (option["value"], locale)
        assert label["en_US"] != option["value"], option["value"]


# ── R2: model picker (static catalogue + custom) ─────────────────────────────


def test_model_is_a_select_with_a_custom_entry(provider_yaml):
    model = credential(provider_yaml, "model")
    assert model["type"] == "select"
    values = [option["value"] for option in model["options"]]
    assert len(values) == len(set(values))
    custom = [value for value in values if value.startswith("__custom")]
    assert len(custom) == 1
    assert values[-1] == custom[0], "the custom entry must be the last option"


def test_every_builtin_engine_has_a_curated_model(provider_yaml):
    engines = {option["value"] for option in credential(provider_yaml, "provider")["options"]}
    model_values = {
        option["value"]
        for option in credential(provider_yaml, "model")["options"]
        if not option["value"].startswith("__custom")
    }
    assert model_values, "the model picker has no catalogue models"
    for value in model_values:
        assert value.startswith("openai_compatible/"), value
    for engine in engines:
        if engine in MODEL_LESS_ENGINES:
            continue  # fixed call shape: the engine itself is the "model"
        assert any(value.startswith(f"{engine}/") for value in model_values), engine


def test_curated_models_come_from_the_fixture(provider_yaml):
    sample = json.loads((ROOT / "scripts/catalog-sources/models-dev-sample.json").read_text(encoding="utf-8"))
    for option in credential(provider_yaml, "model")["options"]:
        value = option["value"]
        if value.startswith("__custom"):
            continue
        engine, _, model_id = value.partition("/")
        assert engine == "openai_compatible", value
        candidates = {model["id"] for provider in sample.values() for model in provider["models"].values()}
        assert model_id in candidates, value


# ── R3: base_url stays an editable text input ────────────────────────────────


def test_base_url_stays_an_editable_text_input(provider_yaml):
    base_url = credential(provider_yaml, "base_url")
    assert base_url["type"] == "text-input"
    assert "options" not in base_url
    assert base_url["required"] is False
    assert base_url["default"] == ""


# ── R4: reasoning picker ─────────────────────────────────────────────────────


def test_reasoning_select_defaults_to_lowest(provider_yaml):
    reasoning = credential(provider_yaml, "reasoning")
    assert reasoning["type"] == "select"
    assert reasoning["default"] == "lowest"
    assert [option["value"] for option in reasoning["options"]] == REASONING_LEVELS


def test_reasoning_lives_in_the_tool_parameters_too(tool_yaml):
    reasoning = param(tool_yaml, "reasoning")
    assert reasoning["type"] == "select"
    assert reasoning["required"] is False
    assert reasoning.get("default", "lowest") == "lowest"
    assert [option["value"] for option in reasoning["options"]] == REASONING_LEVELS


# ── R5: four-locale labels everywhere ────────────────────────────────────────


def _i18n_entries(doc: dict) -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    for entry in doc.get("credentials_schema") or []:
        for field in ("label", "help", "placeholder"):
            if field in entry:
                found.append((f"{entry['name']}.{field}", entry[field]))
        for option in entry.get("options") or []:
            found.append((f"{entry['name']}[{option['value']}]", option["label"]))
    for entry in doc.get("parameters") or []:
        for field in ("label", "human_description", "placeholder"):
            if field in entry:
                found.append((f"{entry['name']}.{field}", entry[field]))
        for option in entry.get("options") or []:
            found.append((f"{entry['name']}[{option['value']}]", option["label"]))
    return found


@pytest.mark.parametrize("relative", ["provider/dualtran.yaml", "tools/dualtran.yaml"])
def test_every_label_exists_in_the_four_dify_locales(relative):
    for name, entry in _i18n_entries(load(relative)):
        assert set(entry) == set(LOCALES), name
        for locale in LOCALES:
            assert str(entry[locale]).strip(), (name, locale)
