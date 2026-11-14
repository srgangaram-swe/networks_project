"""Read bounded event messages without running model work in the traffic process."""

import argparse
import json
import os
import selectors
import signal
import stat
import sys
import time
from pathlib import Path
from threading import Event

from src.artifacts import atomic_json, parse_json
from src.shadow_forecast import ShadowForecast


def consume(descriptor, stop, duration, *, ready=None):
    if not 1 <= duration <= 190:
        raise ValueError("forecast duration must be between 1 and 190 seconds")
    model = ShadowForecast(time.monotonic_ns())
    buffer = bytearray()
    events = 0
    with selectors.DefaultSelector() as poll:
        poll.register(descriptor, selectors.EVENT_READ)
        if ready is not None:
            ready()
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline and not stop.is_set():
            if poll.select(0.02):
                buffer.extend(os.read(descriptor, 65536))
                while b"\n" in buffer:
                    line, _, rest = buffer.partition(b"\n")
                    buffer[:] = rest
                    if len(line) > 512 or events >= 300_000:
                        raise ValueError("forecast event stream exceeds its budget")
                    model.observe(parse_json(line), time.monotonic_ns())
                    events += 1
                if len(buffer) > 512:
                    raise ValueError("forecast event exceeds its byte budget")
            model.advance(time.monotonic_ns())
    result = model.report()
    result.update(events_received=events, partial_event_bytes=len(buffer))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events-fifo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=int, required=True)
    args = parser.parse_args()
    stop = Event()
    previous = {
        number: signal.signal(number, lambda *_: stop.set())
        for number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        if args.output.exists() or args.events_fifo.exists() or args.events_fifo.is_symlink():
            raise ValueError("forecast output and FIFO must be new paths")
        os.mkfifo(args.events_fifo, 0o600)
        with os.fdopen(
            os.open(args.events_fifo, os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW), "rb"
        ) as stream:
            if not stat.S_ISFIFO(os.fstat(stream.fileno()).st_mode):
                raise PermissionError("forecast stream must be a FIFO")
            result = consume(
                stream.fileno(),
                stop,
                args.duration,
                ready=lambda: print(json.dumps({"ready": True}), flush=True),
            )
        atomic_json(args.output, result)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"Shadow forecast failed: {error}", file=sys.stderr)
        return 2
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
