"""Collect Chris's RPC workload as a separate phase on the retained topology."""

import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

from src.artifacts import parse_json
from src.processes import run_command
from src.services import Service


def collect_rpc(bundle, config, backend, cancel):
    """Run RPC after the foreground phase, with a fresh background transfer.

    RPC uses ephemeral client ports and port 5300. It remains best effort in
    the bounded-classification treatment. Its call durations include retries
    and local processing; the foreground RTT estimator never consumes them.
    """
    from src.bulk import server_command, summarize_bulk
    from src.trial import _submit_bulk, unloaded_summary

    seconds = min(config.measurement_seconds, 60)
    bulk_config = replace(config, measurement_seconds=seconds, warmup_seconds=0)
    isolated = config.mode != "loopback"
    common = ("--port", "5300", *(("--allow-isolated",) if isolated else ()))
    script = str(Path(__file__).resolve().parents[1] / "scripts/rpc.py")
    server_args = (
        sys.executable,
        script,
        "server",
        "--bind",
        backend.server_address,
        "--peer",
        backend.client_address,
        "--seconds",
        str(seconds + 8),
        *common,
    )
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=1) as pool:
        responder = stack.enter_context(
            Service(
                backend.command("server", server_args),
                b'"ready":',
                timeout=seconds + 12,
            )
        )
        if config.flows:
            stack.enter_context(
                Service(
                    backend.command(
                        "server",
                        server_command(
                            backend.server_address,
                            config.bulk_port,
                            allow_isolated=isolated,
                        ),
                    ),
                    b"Server listening on",
                    timeout=seconds + 12,
                )
            )
        bulk = _submit_bulk(pool, bulk_config, backend, seconds + 10, cancel)
        try:
            run_command(
                backend.command(
                    "client",
                    (
                        sys.executable,
                        script,
                        "client",
                        "--bind",
                        backend.client_address,
                        "--peer",
                        backend.server_address,
                        "--seconds",
                        str(seconds),
                        "--output",
                        str(bundle.directory / "rpc.json"),
                        *common,
                    ),
                ),
                timeout=seconds + 8,
                stop=cancel,
            )
            responder.check_running()
            bundle.register("rpc.json")
            result = bulk.result(timeout=3) if bulk is not None else None
            bundle.artifact(
                "rpc-bulk.json",
                summarize_bulk(
                    parse_json(result.stdout),
                    bulk_config.bulk_plan(),
                )
                if result
                else unloaded_summary(bulk_config),
            )
            if result:
                bundle.artifact("rpc-bulk-raw.json", parse_json(result.stdout))
            # Let the bounded server finish while SSH still forwards its output.
            # Closing the transport first can discard the final counters.
            responder.result.result(timeout=seconds + 12)
        finally:
            if bulk is not None and not bulk.done():
                cancel.set()
    lines = responder.result.result().stdout.splitlines()
    if not lines:
        raise ValueError("RPC server stopped without retaining its counters")
    server_result = parse_json(lines[-1])
    bundle.artifact("rpc-server.json", server_result)
    if cancel.is_set():
        raise InterruptedError("RPC collection cancelled")
