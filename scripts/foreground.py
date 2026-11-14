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

from src.event_stream import EventWriter
from src.foreground import Workload  # noqa: E402
from src.foreground_io import run_client, run_responder  # noqa: E402
from src.foreground_tcp import run_client as tcp_client  # noqa: E402
from src.foreground_tcp import run_responder as tcp_responder


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


def checked_output(path):
    if path is None:
        raise ValueError("choose a new output file in an existing directory")
    metrics = path.with_name(path.stem + "-transport.json")
    if not path.parent.is_dir() or any(
        item.exists() or item.is_symlink() for item in (path, metrics)
    ):
        raise ValueError("choose new capture and transport files in an existing directory")
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("client", "responder"))
    parser.add_argument("--transport", choices=("udp", "tcp"), default="udp")
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
    parser.add_argument("--start-ns", type=int)
    parser.add_argument("--events-fifo", type=Path)
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
            responder = tcp_responder if args.transport == "tcp" else run_responder
            result = responder(
                (args.bind, port),
                args.peer,
                duration_ms=args.duration_ms,
                allow_isolated=args.allow_isolated,
                stop=stop,
                ready=lambda bind: print(json.dumps({"ready": bind}), file=sys.stderr, flush=True),
            )
        else:
            metrics_path = checked_output(args.output)
            plan = Workload(args.warmup_ms, args.measurement_ms, args.drain_ms, args.rate)
            client = tcp_client if args.transport == "tcp" else run_client
            with EventWriter(args.events_fifo) as writer:
                result = client(
                    plan,
                    (args.bind, port),
                    (args.peer, args.peer_port),
                    allow_isolated=args.allow_isolated,
                    stop=stop,
                    start_ns=args.start_ns,
                    observe=writer,
                )
                metrics = result.pop("transport_metrics", {"transport": "udp"})
                metrics["event_stream"] = {"sent": writer.sent, "dropped": writer.dropped}
                save_result(metrics_path, metrics)
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
