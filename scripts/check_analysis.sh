#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
mkdir -p .local
"$PYTHON" -m ruff check analysis tests/analysis scripts/nucbox_experiment.py
"$PYTHON" -m ruff format --check analysis tests/analysis scripts/nucbox_experiment.py
"$PYTHON" -m coverage run --data-file=.local/analysis-coverage.db --source=analysis \
    -m unittest discover -s tests/analysis -v
"$PYTHON" -m coverage report --data-file=.local/analysis-coverage.db
"$PYTHON" -m coverage json --data-file=.local/analysis-coverage.db -o .local/analysis-branch-report.json
"$PYTHON" scripts/check_branch_coverage.py .local/analysis-branch-report.json
