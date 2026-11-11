#!/usr/bin/env python3
"""Conformance runner for a Python host repo (the `npm run conformance` equivalent).

`node .conformance-kit/run.mjs` assumes the kit sits at `<repo>/.conformance-kit`
and derives the repo root as `../..` from there. In this checkout the plugin is not
two levels below its conformance.json, so run.mjs resolves the wrong root and cannot
find the config. The kit files themselves are unchanged; this runner replays the same
four steps against the plugin root and the same validate.mjs / scan.mjs:

  1. conformance.json is valid and targets the kit's spec
  2. self-test (negative controls) — a gate that cannot fail is worse than none
  3. payloadCommand → JSON on stdout
  4. static scan over the configured files, then validatePayload with the config

Exit code 0 only when the shared validator reports PASS.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
KIT = ROOT / "scripts" / "conformance"
CONFIG_PATH = ROOT / "conformance.json"


def node_binary() -> str:
    node = shutil.which("node")
    if node is None:
        raise SystemExit(
            "node is not on PATH — the shared validator (scripts/conformance/validate.mjs) "
            "is JavaScript and cannot run without it."
        )
    return node


def run_node(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [node_binary(), str(KIT / script), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def load_config() -> dict:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit("conformance.json is missing") from None
    except json.JSONDecodeError as error:
        raise SystemExit(f"conformance.json is invalid: {error}") from error
    spec = run_node("validate.mjs", "--print-schema")
    if spec.returncode != 0:
        raise SystemExit(f"cannot read the kit spec:\n{spec.stderr}")
    kit_spec = json.loads(spec.stdout)["properties"]["spec"]["const"]
    if config.get("spec") != kit_spec:
        raise SystemExit(
            f"conformance.json targets spec {config.get('spec')}, this kit is {kit_spec}"
        )
    return config


def self_test() -> None:
    completed = run_node("validate.mjs", "--self-test")
    if completed.returncode != 0:
        raise SystemExit(f"conformance self-test failed:\n{completed.stderr}")
    print(f"self-test: {completed.stdout.strip()}")


def build_payload(config: dict) -> dict:
    command = config.get("payloadCommand")
    if not command:
        raise SystemExit("conformance.json needs payloadCommand")
    completed = subprocess.run(
        ["bash", "-lc", command], cwd=ROOT, capture_output=True, text=True
    )
    if completed.returncode != 0:
        raise SystemExit(f"payload command failed:\n{completed.stderr}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit(f"payload command did not emit JSON: {error}") from error


def scan_static(config: dict) -> dict:
    """Reuse scan.mjs so the banned-token list stays in the shared kit."""
    static = config.get("static")
    if not static:
        return {"hits": []}
    script = (
        "import { scanFiles } from './scan.mjs';"
        "const [root, config] = process.argv.slice(1);"
        "process.stdout.write(JSON.stringify(scanFiles(root, JSON.parse(config))));"
    )
    completed = run_node("scan.mjs")
    del completed  # only asserting the module is present; the scan runs below
    scan = subprocess.run(
        [node_binary(), "--input-type=module", "-e", script, str(ROOT), json.dumps(static)],
        cwd=KIT,
        input="",
        capture_output=True,
        text=True,
    )
    if scan.returncode != 0:
        raise SystemExit(f"static scan failed:\n{scan.stderr}")
    return {"hits": json.loads(scan.stdout)}


def validate(payload: dict, config: dict) -> int:
    payload = {**payload, "static": {**(payload.get("static") or {}), **scan_static(config)}}
    payload["conformance"] = config
    out = ROOT / "evidence" / "conformance-payload.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    completed = run_node("validate.mjs", str(out))
    if completed.returncode != 0:
        print(completed.stdout.strip())
        print(completed.stderr.strip(), file=sys.stderr)
        return completed.returncode
    print(completed.stdout.strip())
    print(f"payload: {out.relative_to(ROOT)}")
    return 0


def main() -> int:
    config = load_config()
    self_test()
    payload = build_payload(config)
    return validate(payload, config)


if __name__ == "__main__":
    raise SystemExit(main())
