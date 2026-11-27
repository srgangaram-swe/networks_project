"""Linux-only passive header collection on an experiment-owned interface."""

import argparse
import json
import os
import selectors
import signal
import socket
import struct
import sys
import time
from pathlib import Path
from threading import Event

from src.artifacts import atomic_json
from src.event_stream import EventWriter
from src.foreground_io import endpoint
from src.tcp_observation import AckObserver
from src.topology_runtime import require_linux


def collect(client, server, duration, stop, *, events=None, ready=None):
    require_linux()
    endpoint(client, 42001, True)
    endpoint(server, 42000, True)
    if not 1 <= duration <= 190:
        raise ValueError("TCP observer duration must be between 1 and 190 seconds")
    observer = AckObserver(client, server, time.monotonic_ns())
    with (
        socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0800)) as capture,
        selectors.DefaultSelector() as poll,
        EventWriter(events) as writer,
    ):
        capture.bind(("eth0", 0))
        capture.setblocking(False)
        poll.register(capture, selectors.EVENT_READ)
        if ready is not None:
            ready()
        end = time.monotonic() + duration
        next_window = observer.start_ns + 1_000_000_000
        while time.monotonic() < end and not stop.is_set():
            if poll.select(0.02):
                try:
                    data = capture.recv(160)
                except BlockingIOError:
                    continue
                observer.observe(data, time.monotonic_ns())
            now = time.monotonic_ns()
            if now >= next_window:
                index = (now - observer.start_ns) // 1_000_000_000 - 1
                counts = observer.windows.get(index, {})
                writer({"kind": "tcp_window", "observed_ns": now, **counts})
                next_window = now + 1_000_000_000
        received, dropped = struct.unpack("=II", capture.getsockopt(263, 6, 8))
        return {
            **observer.report(),
            "status": "completed",
            "capture_received": received,
            "capture_dropped": dropped,
            "quality": "capture_drops" if dropped else "no_reported_capture_drops",
            "event_stream": {"sent": writer.sent, "dropped": writer.dropped},
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--duration", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--events-fifo", type=Path)
    args = parser.parse_args()
    stop = Event()
    previous = {
        number: signal.signal(number, lambda *_: stop.set())
        for number in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("TCP observer requires a new output file")
        result = collect(
            args.client,
            args.server,
            args.duration,
            stop,
            events=args.events_fifo,
            ready=lambda: print(json.dumps({"ready": True}), flush=True),
        )
        atomic_json(args.output, result)
        owner = args.output.parent.stat()
        if os.geteuid() == 0:
            os.chown(args.output, owner.st_uid, owner.st_gid)
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f"TCP observation failed: {error}", file=sys.stderr)
        return 2
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
