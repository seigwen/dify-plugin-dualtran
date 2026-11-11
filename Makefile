# Dify plugin — Python toolchain. `make conformance` is this repo's `npm run conformance`.
PY ?= python3
VENV := .venv/bin/python

.PHONY: test conformance verify

test:
	$(or $(wildcard $(VENV)),$(PY)) -m pytest tests -q

conformance:
	$(PY) scripts/conformance/run.py

verify: test conformance
