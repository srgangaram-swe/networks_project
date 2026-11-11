#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
if [ "$#" -ne 2 ]; then
    printf '%s\n' 'Usage: timing.sh RUN_COUNT NEW_OUTPUT_DIRECTORY' >&2
    exit 2
fi
PYTHON="${PYTHON:-.venv/bin/python}"
exec "$PYTHON" experiments/cpp_network_testing/probe.py --runs "$1" --output "$2"
