"""Start and join diagnostic observers without changing experimental policies."""

import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path

from src.artifacts import atomic_json, read_json
from src.services import Service


@contextmanager
def observers(bundle, config, backend):
    root = Path(__file__).resolve().parents[1]
    duration = config.warmup_seconds + config.measurement_seconds + 10
    stream = bundle.directory / "events.fifo"
    with ExitStack() as stack:
        if config.shadow_forecast:
            stack.enter_context(
                Service(
                    (
                        sys.executable,
                        str(root / "scripts/shadow_forecast.py"),
                        "--events-fifo",
                        str(stream),
                        "--output",
                        str(bundle.directory / "shadow-forecast.json"),
                        "--duration",
                        str(duration),
                    ),
                    b'"ready":',
                    timeout=duration + 3,
                )
            )
        if config.transport == "tcp" and config.mode != "loopback":
            args = (
                sys.executable,
                str(root / "scripts/tcp_observer.py"),
                "--client",
                backend.client_address,
                "--server",
                backend.server_address,
                "--duration",
                str(duration),
                "--output",
                str(bundle.directory / "tcp-observer.json"),
            )
            if config.shadow_forecast:
                args += ("--events-fifo", str(stream))
            stack.enter_context(
                Service(backend.command("client", args), b'"ready":', timeout=duration + 3)
            )
        yield
    bundle.register("foreground-transport.json")
    if config.transport == "tcp" and config.mode != "loopback":
        bundle.register("tcp-observer.json")
    if config.shadow_forecast:
        forecast = read_json(bundle.directory / "shadow-forecast.json")
        foreground = read_json(bundle.directory / "foreground-transport.json")
        dropped = foreground["event_stream"]["dropped"]
        if (bundle.directory / "tcp-observer.json").exists():
            dropped += read_json(bundle.directory / "tcp-observer.json")["event_stream"]["dropped"]
        forecast["producer_events_dropped"] = dropped
        forecast["quality"] = "incomplete_event_stream" if dropped else "no_reported_event_drops"
        atomic_json(bundle.directory / "shadow-forecast.json", forecast)
        bundle.register("shadow-forecast.json")
        stream.unlink()
