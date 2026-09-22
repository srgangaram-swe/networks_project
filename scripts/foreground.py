"""Run a foreground endpoint on loopback or an explicitly authorized testbed."""

import argparse
import json
import os
import signal
import sys
import tempfile
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.foreground import Workload  # noqa: E402
from src.foreground_io import run_client, run_responder  # noqa: E402


def save_result(path: Path, result: dict) -> None:
    """Publish a complete file without replacing an earlier observation."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(result, stream, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("client", "responder"))
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--peer", default="127.0.0.1")
    parser.add_argument("--peer-port", type=int, default=42000)
    parser.add_argument("--allow-isolated", action="store_true")
    parser.add_argument("--warmup-ms", type=int, default=10000)
    parser.add_argument("--measurement-ms", type=int, default=60000)
    parser.add_argument("--drain-ms", type=int, default=2000)
    parser.add_argument("--rate", type=int, default=500)
    parser.add_argument("--duration-ms", type=int, default=90000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    stop = Event()
    previous = {}

    def cancel(signum, frame):
        stop.set()

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, cancel)
        port = (
            args.port if args.port is not None else (42000 if args.role == "responder" else 42001)
        )
        if args.role == "responder":
            if port == 0:
                raise ValueError("choose an explicit responder port")
            result = run_responder(
                (args.bind, port),
                args.peer,
                duration_ms=args.duration_ms,
                allow_isolated=args.allow_isolated,
                stop=stop,
                ready=lambda bind: print(json.dumps({"ready": bind}), file=sys.stderr, flush=True),
            )
        else:
            if args.output is None or not args.output.parent.is_dir() or args.output.exists():
                raise ValueError("choose a new output file in an existing directory")
            plan = Workload(args.warmup_ms, args.measurement_ms, args.drain_ms, args.rate)
            result = run_client(
                plan,
                (args.bind, port),
                (args.peer, args.peer_port),
                allow_isolated=args.allow_isolated,
                stop=stop,
            )
            save_result(args.output, result)
        print(json.dumps({key: result[key] for key in ("status", "counts", "bind")}))
        return {"completed": 0, "cancelled": 130, "io_error": 2}[result["status"]]
    except (ValueError, OSError) as exc:
        print(f"Foreground endpoint failed: {exc}", file=sys.stderr)
        return 2
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
