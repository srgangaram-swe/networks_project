"""Bounded per-call diagnostics for the experimental RPC packet protocol."""

from dataclasses import asdict, dataclass

MAX_RECORDS = 100_000
MAX_TIMESTAMP_NS = 2**63 - 1
MAX_RETRANSMISSIONS = 20
OUTCOMES = frozenset({"completed", "timeout", "cancelled", "io_error"})
QUANTILES = {"p50_ms": 500, "p95_ms": 950, "p99_ms": 990, "p999_ms": 999}


def _integer(value: int, name: str, maximum: int) -> None:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 0 and {maximum}")


def _nearest_rank(values: list[int], per_thousand: int) -> float | None:
    """Return a nearest-rank percentile in milliseconds from sorted nanoseconds."""
    if not values:
        return None
    rank = (per_thousand * len(values) + 999) // 1000
    return values[rank - 1] / 1_000_000


def _counters(raw: dict[str, int] | None, name: str) -> dict[str, int] | None:
    """Copy a client or server counter snapshot after validating its values."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{name} must be a counter dictionary")
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{name} contains an invalid counter name")
        _integer(value, f"{name}[{key}]", 2**64 - 1)
    return dict(raw)


@dataclass(frozen=True)
class RpcCallRecord:
    """One application call measured using the client's monotonic clock.

    Duration includes retransmissions and local processing. It is not a
    network-only RTT. Timeouts and other failures retain their duration but
    do not contribute to the successful-call latency percentiles.
    """

    machine_id: int
    activity_id: int
    sequence: int
    started_ns: int
    finished_ns: int
    outcome: str
    retransmissions: int = 0

    def __post_init__(self) -> None:
        _integer(self.machine_id, "machine_id", 2**64 - 1)
        _integer(self.activity_id, "activity_id", 2**32 - 1)
        _integer(self.sequence, "sequence", 2**64 - 1)
        _integer(self.started_ns, "started_ns", MAX_TIMESTAMP_NS)
        _integer(self.finished_ns, "finished_ns", MAX_TIMESTAMP_NS)
        _integer(self.retransmissions, "retransmissions", MAX_RETRANSMISSIONS)
        if self.finished_ns < self.started_ns:
            raise ValueError("call finish cannot precede its start")
        if self.outcome not in OUTCOMES:
            raise ValueError("unsupported RPC call outcome")

    @property
    def duration_ns(self) -> int:
        return self.finished_ns - self.started_ns


class RpcMetrics:
    """Collect bounded call records and summarize development measurements.

    The caller records a call after run_client() returns or raises, using
    monotonic timestamps and the change in the client's retransmission count.
    Protocol counter snapshots may be supplied separately at summary time.
    """

    def __init__(self, max_records: int = MAX_RECORDS) -> None:
        _integer(max_records, "max_records", MAX_RECORDS)
        if max_records == 0:
            raise ValueError("max_records must be positive")
        self.max_records = max_records
        self.records: list[RpcCallRecord] = []
        self._seen: set[tuple[int, int, int]] = set()

    def add(self, record: RpcCallRecord) -> None:
        """Store one unique call or reject a duplicate or an oversized run."""
        if not isinstance(record, RpcCallRecord):
            raise TypeError("record must be an RpcCallRecord")
        if len(self.records) >= self.max_records:
            raise ValueError("RPC call record limit exceeded")
        key = (record.machine_id, record.activity_id, record.sequence)
        if key in self._seen:
            raise ValueError("duplicate RPC call identifier")
        self._seen.add(key)
        self.records.append(record)

    def summarize(
            self,
            *,
            client_counts: dict[str, int] | None = None,
            server_counts: dict[str, int] | None = None,
    ) -> dict:
        """Report successful-call latency, failures, and protocol counters."""
        completed = sorted(
            record.duration_ns for record in self.records if record.outcome == "completed"
        )
        counts = {
            outcome: sum(record.outcome == outcome for record in self.records)
            for outcome in ("completed", "timeout", "cancelled", "io_error")
        }
        total = len(self.records)
        result = {
            "schema_version": 1,
            "purpose": "rpc_development_diagnostics",
            "eligible_for_primary": False,
            "latency_definition": "application_call_start_to_finish",
            "calls": total,
            "counts": counts,
            "timeout_rate": counts["timeout"] / total if total else None,
            "failure_rate": (total - counts["completed"]) / total if total else None,
            "retransmissions": sum(record.retransmissions for record in self.records),
            "client_counts": _counters(client_counts, "client_counts"),
            "server_counts": _counters(server_counts, "server_counts"),
        }
        result.update({name: _nearest_rank(completed, rank) for name, rank in QUANTILES.items()})
        return result

    def request_rows(self) -> list[dict]:
        """Export one JSON-compatible row per recorded RPC call."""
        return [
            {**asdict(record), "duration_ms": record.duration_ns / 1_000_000}
            for record in self.records
        ]
