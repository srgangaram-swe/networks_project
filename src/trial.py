"""Portable diagnostic trials with separate Linux topology ownership."""

import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event

from src.artifacts import parse_json, read_json
from src.bulk import BulkPlan, client_command, server_command, summarize_bulk
from src.cpu import cpu_usage, snapshot_cpu
from src.experiment_config import bounded_integer
from src.foreground import Workload
from src.foreground_io import endpoint
from src.processes import CommandError, run_command
from src.run_bundle import RunBundle, source_identity
from src.services import Service
from src.testbed_backend import Backend

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class TrialConfig:
    mode: str = "loopback"
    policy: str = "none"
    measurement_seconds: int = 2
    warmup_seconds: int = 0
    flows: int = 1
    aggregate_bps: int = 8_000_000
    foreground_port: int = 42000
    bulk_port: int = 5201

    def __post_init__(self) -> None:
        bounded_integer(self.measurement_seconds, "measurement_seconds", 1, 120)
        bounded_integer(self.warmup_seconds, "warmup_seconds", 0, 60)
        if (self.flows, self.aggregate_bps) != (0, 0):
            self.bulk_plan()
        elif type(self.flows) is not int or type(self.aggregate_bps) is not int:
            raise ValueError("unloaded trials require integer zero flows and demand")
        self.foreground_plan()
        if self.mode not in {"loopback", "namespace"}:
            raise ValueError("mode must be loopback or namespace")
        if self.mode == "loopback" and self.policy != "none":
            raise ValueError("loopback measurements have no queue policy")
        if self.mode == "namespace" and self.foreground_port != 42000:
            raise ValueError("the namespace classification contract requires foreground port 42000")
        for port in (self.foreground_port, self.bulk_port):
            endpoint("127.0.0.1", port)
            if port == 0:
                raise ValueError("choose explicit service ports")

    def bulk_plan(self) -> BulkPlan:
        return BulkPlan(
            self.aggregate_bps, self.flows, self.measurement_seconds, self.warmup_seconds
        )

    def foreground_plan(self) -> Workload:
        return Workload(self.warmup_seconds * 1000, self.measurement_seconds * 1000, 2000, 500)


def _foreground_command(
    config: TrialConfig, backend: Backend, bundle: RunBundle, start: int
) -> tuple[str, ...]:
    args = (
        sys.executable,
        str(ROOT / "scripts/foreground.py"),
        "client",
        "--bind",
        backend.client_address,
        "--port",
        "42001" if config.mode == "namespace" else "0",
        "--peer",
        backend.server_address,
        "--peer-port",
        str(config.foreground_port),
        "--warmup-ms",
        str(config.warmup_seconds * 1000),
        "--measurement-ms",
        str(config.measurement_seconds * 1000),
        "--drain-ms",
        "2000",
        "--start-ns",
        str(start),
        "--output",
        str(bundle.directory / "foreground.json"),
    )
    return backend.command(
        "client", args + (("--allow-isolated",) if config.mode == "namespace" else ())
    )


def _start_services(stack: ExitStack, config: TrialConfig, backend: Backend) -> Service:
    isolated = config.mode == "namespace"
    duration = config.warmup_seconds + config.measurement_seconds + 10
    responder_args = (
        sys.executable,
        str(ROOT / "scripts/foreground.py"),
        "responder",
        "--bind",
        backend.server_address,
        "--port",
        str(config.foreground_port),
        "--peer",
        backend.client_address,
        "--duration-ms",
        str(duration * 1000),
    ) + (("--allow-isolated",) if isolated else ())
    responder = stack.enter_context(
        Service(backend.command("server", responder_args), b'"ready":', timeout=duration + 3)
    )
    if config.flows:
        server = backend.command(
            "server",
            server_command(backend.server_address, config.bulk_port, allow_isolated=isolated),
        )
        stack.enter_context(Service(server, b"Server listening on", timeout=duration + 3))
    return responder


def _phase(
    bundle: RunBundle, state: str, deadline_ns: int, cancel: Event, futures: list[Future]
) -> None:
    bundle.transition(state)
    while time.monotonic_ns() < deadline_ns:
        if cancel.wait(min(0.05, max(0, (deadline_ns - time.monotonic_ns()) / 1e9))):
            raise InterruptedError("trial cancelled")
        for future in futures:
            if future.done():
                future.result()


def _collect_workloads(
    bundle: RunBundle, config: TrialConfig, backend: Backend, cancel: Event
) -> None:
    with ExitStack() as services, ThreadPoolExecutor(max_workers=2) as pool:
        responder = _start_services(services, config, backend)
        start = time.monotonic_ns() + 250_000_000
        measurement = start + config.warmup_seconds * 1_000_000_000
        drain = measurement + config.measurement_seconds * 1_000_000_000
        end = drain + 2_000_000_000
        bundle.manifest["phases"] = {
            "start_ns": start,
            "measurement_start_ns": measurement,
            "measurement_end_ns": drain,
            "end_ns": end,
        }
        bundle.save()
        deadline = config.warmup_seconds + config.measurement_seconds + 10
        foreground_future = pool.submit(
            run_command,
            _foreground_command(config, backend, bundle, start),
            timeout=deadline,
            stop=cancel,
        )
        bulk_future = _submit_bulk(pool, config, backend, deadline, cancel)
        futures = [foreground_future] + ([bulk_future] if bulk_future is not None else [])
        try:
            _phase(bundle, "warmup", measurement, cancel, futures)
            before = snapshot_cpu()
            _phase(bundle, "measurement", drain, cancel, futures)
            after = snapshot_cpu()
            _phase(bundle, "drain", end, cancel, futures)
            foreground_future.result(timeout=3)
            bulk_result = bulk_future.result(timeout=3) if bulk_future is not None else None
            responder.check_running()
            bundle.transition("collection")
            bundle.register("foreground.json")
            bundle.artifact(
                "bulk.json",
                summarize_bulk(parse_json(bulk_result.stdout), config.bulk_plan())
                if bulk_result is not None
                else unloaded_summary(config),
            )
            bundle.artifact("cpu.json", cpu_usage(before, after))
        finally:
            # Stop both owned children before leaving the executor or removing
            # namespaces, even when another child failed first.
            if any(not future.done() for future in futures):
                cancel.set()


def _submit_bulk(pool, config: TrialConfig, backend: Backend, deadline: int, cancel: Event):
    if not config.flows:
        return None
    isolated = config.mode == "namespace"
    command = backend.command(
        "client",
        client_command(
            config.bulk_plan(),
            backend.client_address,
            backend.server_address,
            config.bulk_port,
            linux=isolated,
            allow_isolated=isolated,
        ),
    )
    return pool.submit(run_command, command, timeout=deadline, stop=cancel)


def unloaded_summary(config: TrialConfig) -> dict:
    """A planned absence of bulk traffic, rather than a missing receiver report."""
    return {
        "requested": {
            "aggregate_bps": 0,
            "flows": 0,
            "measurement_seconds": config.measurement_seconds,
            "warmup_seconds": config.warmup_seconds,
        },
        "per_flow_bps": 0,
        "actual_flows": 0,
        "receiver_bytes": 0,
        "receiver_seconds": config.measurement_seconds,
        "goodput_mbps": 0,
        "intervals": [],
        "tool_version": "not_started",
        "exit_status": 0,
        "window": "foreground",
        "foreground_window_aligned": True,
    }


def run_trial(directory: Path, config: TrialConfig, cancel: Event | None = None) -> dict:
    from src.bundle_validation import validate_contents

    cancel = cancel if cancel is not None else Event()
    directory = directory.absolute()
    bundle = RunBundle(directory, asdict(config), source_identity(ROOT))
    backend = Backend(config.mode, config.policy, directory)
    primary_error = None
    try:
        bundle.transition("preflight")
        if config.flows:
            run_command(("iperf3", "--version"), limit=16384)
        bundle.transition("setup")
        backend.setup()
        bundle.artifact("queues-before.json", backend.snapshot())
        _collect_workloads(bundle, config, backend, cancel)
        bundle.artifact("queues-after.json", backend.snapshot())
        bundle.transition("validation")
        validate_contents(bundle.directory, bundle.manifest)
        bundle.manifest["validity"]["reasons"].append("hardware_calibration_pending")
        if config.flows:
            bundle.manifest["validity"]["reasons"].append("bulk_window_alignment_pending")
        if config.mode == "loopback":
            bundle.manifest["validity"]["reasons"].append("loopback_diagnostic")
        bundle.transition("teardown")
        backend.close()
        bundle.transition("completed")
    except (OSError, ValueError, RuntimeError, TimeoutError, KeyboardInterrupt) as exc:
        primary_error = exc
        bundle.fail(exc, cancelled=isinstance(exc, (KeyboardInterrupt, InterruptedError)))
        raise
    finally:
        try:
            backend.close()
        except (OSError, RuntimeError) as exc:
            bundle.manifest["errors"].append({"type": "cleanup_error", "message": str(exc)[:1024]})
            bundle.save()
            if primary_error is None:
                raise CommandError("topology cleanup failed; retain the ownership journal") from exc
            primary_error.add_note(f"topology cleanup also failed: {exc}")
    return read_json(directory / "manifest.json")
