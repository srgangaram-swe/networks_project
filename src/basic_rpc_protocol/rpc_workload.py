"""Bounded RPC request workload for network experiment development."""

import secrets
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from itertools import count
from threading import BoundedSemaphore, Event, Lock, local

from src.experiment_config import bounded_integer
from src.foreground_io import endpoint

from .rpc_client import RpcClient, RpcTimeout
from .rpc_connector import run_client
from .rpc_metrics import MAX_RECORDS, RpcCallRecord, RpcMetrics
from .rpc_packet_protocol import MAX_PAYLOAD_BYTES

DEFAULT_REQUESTS_PER_SECOND = 500
DEFAULT_MEASUREMENT_SECONDS = 60
DEFAULT_WORKERS = 32
DEFAULT_RETRY_TIMEOUT_MS = 250
DEFAULT_MAX_RETRIES = 3
DEFAULT_TOTAL_TIMEOUT_MS = 2_000
MAX_WORKERS = 256


@dataclass(frozen=True)
class RpcWorkloadConfig:
    """Parameters for a bounded, open-loop sequence of RPC echo calls.

    Each call has one 512-byte wire request when the default 482-byte
    payload is used. Responses have the same size with an echo server.
    The extra 30-byte ACK is separate protocol traffic.
    """

    bind: tuple[str, int] = ("127.0.0.1", 0)
    peer: tuple[str, int] = ("127.0.0.1", 5300)
    requests_per_second: int = DEFAULT_REQUESTS_PER_SECOND
    measurement_seconds: int = DEFAULT_MEASUREMENT_SECONDS
    workers: int = DEFAULT_WORKERS
    machine_id: int | None = None
    payload: bytes = b"\x00" * MAX_PAYLOAD_BYTES
    retry_timeout_ms: int = DEFAULT_RETRY_TIMEOUT_MS
    max_retries: int = DEFAULT_MAX_RETRIES
    total_timeout_ms: int = DEFAULT_TOTAL_TIMEOUT_MS
    allow_isolated: bool = False

    def __post_init__(self) -> None:
        """Validate endpoints, scheduling limits, and RPC packet sizes."""
        if type(self.allow_isolated) is not bool:
            raise ValueError("allow_isolated must be a boolean")
        bind = endpoint(*self.bind, self.allow_isolated)
        peer = endpoint(*self.peer, self.allow_isolated)
        if bind[1] != 0:
            raise ValueError("bind must use port 0 for concurrent client sockets")
        if peer[1] == 0 or bind == peer:
            raise ValueError("peer must identify a distinct server endpoint")

        bounded_integer(self.requests_per_second, "requests_per_second", 1, 1_000)
        bounded_integer(self.measurement_seconds, "measurement_seconds", 1, 120)
        bounded_integer(self.workers, "workers", 1, MAX_WORKERS)
        bounded_integer(self.retry_timeout_ms, "retry_timeout_ms", 1, 60_000)
        bounded_integer(self.max_retries, "max_retries", 0, 20)
        bounded_integer(self.total_timeout_ms, "total_timeout_ms", 1, 200_000)
        if self.requests_per_second * self.measurement_seconds > MAX_RECORDS:
            raise ValueError("scheduled RPC calls exceed the metrics record limit")
        if self.total_timeout_ms <= self.retry_timeout_ms * (self.max_retries + 1):
            raise ValueError("total_timeout_ms must exceed the full retry interval")
        if self.machine_id is not None:
            bounded_integer(self.machine_id, "machine_id", 0, 2**64 - 1)
        if not isinstance(self.payload, bytes) or len(self.payload) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"payload must contain at most {MAX_PAYLOAD_BYTES} bytes")


def _wait_until(deadline_ns: int, stop: Event) -> bool:
    """Wait until a monotonic deadline, with periodic cancellation checks."""
    while not stop.is_set():
        remaining_ns = deadline_ns - time.monotonic_ns()
        if remaining_ns <= 0:
            return True
        stop.wait(min(remaining_ns / 1_000_000_000, 0.02))
    return False


def run_rpc_workload(
    config: RpcWorkloadConfig,
    *,
    stop: Event | None = None,
) -> dict:
    """Issue rate-paced RPC echo calls and return per-call diagnostics.

    Workers retain separate client activities and execute at most one call
    per activity. When every worker is occupied, a scheduled call is
    skipped instead of entering an unbounded queue. Calls in flight are
    allowed to finish after the measurement window closes.

    The server must already be running. This is development-only output,
    not an artifact accepted as a primary experiment measurement.
    """
    if not isinstance(config, RpcWorkloadConfig):
        raise TypeError("config must be an RpcWorkloadConfig")
    stop = stop if stop is not None else Event()
    machine_id = config.machine_id if config.machine_id is not None else secrets.randbits(64)
    workers = _CallWorkers(config, stop, machine_id)
    scheduled = config.requests_per_second * config.measurement_seconds
    start_ns = time.monotonic_ns()
    futures, skipped_capacity, status = _schedule(config, stop, workers, start_ns)
    return _results(config, machine_id, scheduled, start_ns, futures, skipped_capacity, status)


def _schedule(config, stop, workers, start_ns):
    capacity = BoundedSemaphore(config.workers)
    futures = []
    skipped_capacity = 0
    status = "completed"
    scheduled = config.requests_per_second * config.measurement_seconds
    with ThreadPoolExecutor(max_workers=config.workers) as executor:
        for index in range(scheduled):
            target_ns = start_ns + index * 1_000_000_000 // config.requests_per_second
            if not _wait_until(target_ns, stop):
                status = "cancelled"
                break
            if not capacity.acquire(blocking=False):
                skipped_capacity += 1
                continue
            try:
                future = executor.submit(workers.execute_call, target_ns)
            except BaseException:
                capacity.release()
                raise
            future.add_done_callback(lambda completed: capacity.release())
            futures.append(future)

    return futures, skipped_capacity, status


def _results(config, machine_id, scheduled, start_ns, futures, skipped_capacity, status):
    client_rotations = 0
    metrics = RpcMetrics(max_records=scheduled)
    counts: Counter[str] = Counter()
    start_lag_ns = []
    rows = []
    for future in as_completed(futures):
        record, differences, lag_ns, rotated = future.result()
        metrics.add(record)
        counts.update(differences)
        start_lag_ns.append(lag_ns)
        client_rotations += int(rotated)
        rows.append((record, lag_ns))

    # Present records in start-time order rather than thread completion order.
    rows.sort(key=lambda entry: entry[0].started_ns)
    result_rows = [
        {
            "machine_id": record.machine_id,
            "activity_id": record.activity_id,
            "sequence": record.sequence,
            "started_ns": record.started_ns,
            "finished_ns": record.finished_ns,
            "duration_ms": record.duration_ns / 1_000_000,
            "start_lag_ms": lag_ns / 1_000_000,
            "outcome": record.outcome,
            "retransmissions": record.retransmissions,
        }
        for record, lag_ns in rows
    ]
    summary = metrics.summarize(client_counts=dict(counts))
    return {
        "schema_version": 1,
        "purpose": "rpc_development_diagnostics",
        "eligible_for_primary": False,
        "status": status,
        "machine_id": machine_id,
        "requests_per_second": config.requests_per_second,
        "measurement_seconds": config.measurement_seconds,
        "workers": config.workers,
        "payload_bytes": len(config.payload),
        "scheduled_calls": scheduled,
        "admitted_calls": len(futures),
        "skipped_capacity": skipped_capacity,
        "cancelled_before_admission": scheduled - len(futures) - skipped_capacity,
        "client_rotations": client_rotations,
        "max_start_lag_ms": max(start_lag_ns, default=0) / 1_000_000,
        "elapsed_seconds": (time.monotonic_ns() - start_ns) / 1_000_000_000,
        "summary": summary,
        "requests": result_rows,
    }


class _CallWorkers:
    """Own one activity per worker and rotate abandoned client state."""

    def __init__(self, config, stop, machine_id):
        self.config, self.stop, self.machine_id = config, stop, machine_id
        self.activities = count(1)
        self.activity_lock = Lock()
        self.thread_state = local()

    def new_client(self) -> RpcClient:
        """Assign a fresh activity when a worker starts or abandons a call."""
        with self.activity_lock:
            activity_id = next(self.activities)
        if activity_id > 2**32 - 1:
            raise OverflowError("RPC activity identifier space exhausted")
        return RpcClient(
            self.machine_id,
            activity_id,
            timeout_ns=self.config.retry_timeout_ms * 1_000_000,
            max_retries=self.config.max_retries,
        )

    def execute_call(self, scheduled_ns: int) -> tuple[RpcCallRecord, dict[str, int], int, bool]:
        """Execute one call and measure its latency and counter changes."""
        config, stop = self.config, self.stop
        thread_state = self.thread_state
        client = getattr(thread_state, "client", None)
        if client is None:
            client = self.new_client()
            thread_state.client = client

        before = client.statistics()
        sequence = client.sequence + 1
        started_ns = time.monotonic_ns()
        outcome = "completed"
        rotate = False

        try:
            response = run_client(
                client,
                config.payload,
                config.bind,
                config.peer,
                allow_isolated=config.allow_isolated,
                stop=stop,
                total_timeout_ms=config.total_timeout_ms,
            )
            if response != config.payload:
                raise ValueError("RPC echo response does not match the request")
        except RpcTimeout:
            outcome = "timeout"
        except TimeoutError:
            outcome = "timeout"
            rotate = True
        except InterruptedError:
            outcome = "cancelled"
            rotate = True
        except OSError:
            outcome = "io_error"
            rotate = True
        finally:
            finished_ns = time.monotonic_ns()

        after = client.statistics()
        differences = {
            key: value - before.get(key, 0)
            for key, value in after.items()
            if value > before.get(key, 0)
        }
        record = RpcCallRecord(
            machine_id=client.machine_id,
            activity_id=client.activity_id,
            sequence=sequence,
            started_ns=started_ns,
            finished_ns=finished_ns,
            outcome=outcome,
            retransmissions=differences.get("retransmissions", 0),
        )

        # A hard timeout or socket failure can leave a call outstanding.
        # Never reuse that activity with a reset sequence number.
        if rotate or client.has_pending_call:
            thread_state.client = self.new_client()
            rotate = True
        return record, differences, max(0, started_ns - scheduled_ns), rotate
