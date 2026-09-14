#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
"$PYTHON" -m ruff check src scripts tests
"$PYTHON" -m ruff format --check src scripts tests
"$PYTHON" -m coverage erase
"$PYTHON" -m coverage run -m unittest discover -s tests/unit -v
"$PYTHON" -m coverage run --append -m unittest discover -s tests/integration -v
"$PYTHON" -m coverage report
"$PYTHON" scripts/validate_config.py configs/primary.json
"$PYTHON" scripts/check_repository.py
sh -n scripts/check.sh
git diff --check
