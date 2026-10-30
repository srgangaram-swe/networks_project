#!/usr/bin/env bash
set -euo pipefail

# Run from the project directory (where build/server and build/client live).
SERVER="./build/server"
CLIENT="./build/client"
RUNS="${1:-10}"
OUTPUT="timings.csv"

if [[ ! "$RUNS" =~ ^[1-9][0-9]*$ ]]; then
    echo "Usage: $0 [number_of_runs]" >&2
    exit 1
fi

if [[ ! -x "$SERVER" || ! -x "$CLIENT" ]]; then
    echo "Build the server and client first: cmake -S . -B build && cmake --build build" >&2
    exit 1
fi

TEMP_DIR=$(mktemp -d)
SERVER_PID=""
cleanup() {
    if [[ -n "$SERVER_PID" ]]; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

printf 'run,rtt_ms\n' > "$OUTPUT"

for ((i = 1; i <= RUNS; i++)); do
    "$SERVER" > "$TEMP_DIR/server.log" 2>&1 &
    SERVER_PID=$!

    sleep 0.2  # Allow server to start listening before connecting.

    if ! "$CLIENT" > "$TEMP_DIR/client.log" 2>&1; then
        echo "Client failed on run $i:" >&2
        cat "$TEMP_DIR/server.log" "$TEMP_DIR/client.log" >&2
        exit 1
    fi

    if ! wait "$SERVER_PID"; then
        SERVER_PID=""
        echo "Server failed on run $i:" >&2
        cat "$TEMP_DIR/server.log" >&2
        exit 1
    fi
    SERVER_PID=""

    # Extract the timing line, e.g. '0.2354ms', from the server output.
    TIME_MS=$(sed -nE 's/^[[:space:]]*([0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?)ms[[:space:]]*$/\1/p' "$TEMP_DIR/server.log" | tail -n 1)
    if [[ -z "$TIME_MS" ]]; then
        echo "No timing value found on run $i:" >&2
        cat "$TEMP_DIR/server.log" >&2
        exit 1
    fi

    printf '%d,%s\n' "$i" "$TIME_MS" >> "$OUTPUT"
    echo "Run $i: $TIME_MS ms"
done

echo "Saved $RUNS measurements to $OUTPUT"