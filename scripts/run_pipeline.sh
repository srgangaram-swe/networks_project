#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
    sh scripts/setup_environment.sh
fi
exec .venv/bin/python scripts/pipeline.py "$@"
