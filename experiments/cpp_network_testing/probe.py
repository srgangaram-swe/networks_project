"""Bounded loopback timing for Chris Ong's PING/PONG/ACK prototype."""

import argparse
import csv
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.artifacts import atomic_json  # noqa: E402
from src.processes import run_command  # noqa: E402
from src.services import Service  # noqa: E402


def run(build: Path, output: Path, runs: int) -> list[float]:
    if type(runs) is not int or not 1 <= runs <= 100:
        raise ValueError("choose 1 to 100 prototype trials")
    server, client = (str((build / name).resolve()) for name in ("server", "client"))
    output.mkdir(mode=0o700)
    values = []
    state = {"state": "running", "kind": "cpp_loopback_smoke", "eligible_for_primary": False}
    atomic_json(output / "status.json", state)
    try:
        for index in range(runs):
            with Service((server,), b"Server waiting", timeout=10) as service:
                result = run_command((client,), timeout=5, limit=8192)
                observed = service.result.result(timeout=3)
            (output / f"server-{index:03d}.txt").write_bytes(observed.stdout)
            (output / f"client-{index:03d}.txt").write_bytes(result.stdout)
            match = re.search(rb"^([0-9.eE+\-]+)ms$", observed.stdout, re.MULTILINE)
            if match is None:
                raise ValueError("prototype server did not report its acknowledgment RTT")
            value = float(match[1])
            if not math.isfinite(value) or value < 0:
                raise ValueError("invalid prototype RTT")
            values.append(value)
        with (output / "timings.csv").open("x", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("run", "server_pong_to_ack_ms"))
            writer.writerows(enumerate(values, 1))
        state.update(state="completed", runs=runs)
        atomic_json(output / "status.json", state)
    except (OSError, ValueError, RuntimeError, TimeoutError, KeyboardInterrupt) as error:
        state.update(
            state="cancelled" if isinstance(error, KeyboardInterrupt) else "failed",
            error_type=type(error).__name__,
        )
        try:
            atomic_json(output / "status.json", state)
        except (OSError, ValueError) as persistence:
            error.add_note(f"prototype status could not be saved: {persistence}")
        raise
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=Path("build/cpp-network-probe"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        values = run(args.build_dir, args.output, args.runs)
        print(f"Completed {len(values)} loopback prototype trials in {args.output}")
    except KeyboardInterrupt:
        print("Prototype cancelled", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        print(f"Prototype failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
