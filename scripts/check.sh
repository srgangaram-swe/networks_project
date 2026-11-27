#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
"$PYTHON" -m ruff check src scripts tests analysis
"$PYTHON" -m ruff format --check src scripts tests analysis
"$PYTHON" -m ruff check experiments/cpp_network_testing
"$PYTHON" -m ruff format --check experiments/cpp_network_testing
"$PYTHON" -m coverage erase
"$PYTHON" -m coverage run -m unittest discover -s tests/unit -v
"$PYTHON" -m coverage run --append -m unittest discover -s tests/integration -v
"$PYTHON" -m coverage run --append -m unittest discover -s tests/linux -v
"$PYTHON" -m coverage report
mkdir -p .local
"$PYTHON" -m coverage json -o .local/coverage.json
"$PYTHON" scripts/check_branch_coverage.py .local/coverage.json
"$PYTHON" scripts/validate_config.py configs/primary.json
"$PYTHON" scripts/verify_testbed_contract.py
"$PYTHON" scripts/check_repository.py
sh -n scripts/check.sh
sh -n scripts/setup_nucbox.sh
sh -n scripts/check_analysis.sh
sh -n scripts/setup_environment.sh
sh -n scripts/run_pipeline.sh
git diff --check
