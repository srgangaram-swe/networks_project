#!/bin/sh
# Use a supported interpreter without replacing the machine's Python.
set -eu
cd "$(dirname "$0")/.."
if [ -n "${PYTHON:-}" ]; then
    bootstrap_python="$PYTHON"
elif [ -x .venv/bin/python ]; then
    bootstrap_python=.venv/bin/python
elif command -v python3.12 >/dev/null 2>&1; then
    bootstrap_python=python3.12
else
    bootstrap_python=python3
fi
if ! "$bootstrap_python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    printf '%s\n' 'Python 3.12+ is required. Set PYTHON to that interpreter and rerun.' >&2
    exit 2
fi
exec "$bootstrap_python" scripts/setup_environment.py "$@"
