"""Candidate v1 request records for the foreground workload and analysis."""

from dataclasses import dataclass
from typing import Any

from src.experiment_config import bounded_integer

CONTRACT_VERSION = 1
TIMEOUT_NS = 1_000_000_000
WARMUP_SECONDS = 10
DRAIN_SECONDS = 2
MAX_IN_FLIGHT = 1024
MAX_TIMESTAMP_NS = 2**63 - 1
FIELDS = frozenset({"schema_version", "request_id", "scheduled_ns", "sent_ns", "received_ns"})


@dataclass(frozen=True)
class RequestRecord:
    """One scheduled request; timestamps share the client's monotonic clock.

    A missing send records generator overload. A late response remains a timeout
    for deadline accounting, but keeps its receive timestamp for diagnosis.
    Duplicate replies belong in the event log, not in extra request records.
    """

    request_id: int
    scheduled_ns: int
    sent_ns: int | None
    received_ns: int | None

    @classmethod
    def from_mapping(cls, raw: Any) -> "RequestRecord":
        if not isinstance(raw, dict) or raw.keys() != FIELDS:
            raise ValueError("request record must contain exactly the v1 fields")
        bounded_integer(raw["schema_version"], "schema_version", CONTRACT_VERSION, CONTRACT_VERSION)
        request_id = bounded_integer(raw["request_id"], "request_id", 0, 2**64 - 1)
        scheduled = bounded_integer(raw["scheduled_ns"], "scheduled_ns", 0, MAX_TIMESTAMP_NS)
        sent = raw["sent_ns"]
        received = raw["received_ns"]
        if sent is not None:
            bounded_integer(sent, "sent_ns", scheduled, MAX_TIMESTAMP_NS - TIMEOUT_NS)
        if received is not None:
            if sent is None:
                raise ValueError("a response requires a sent request")
            bounded_integer(received, "received_ns", sent, MAX_TIMESTAMP_NS)
        return cls(request_id, scheduled, sent, received)

    @property
    def outcome(self) -> str:
        if self.sent_ns is None:
            return "not_sent"
        if self.received_ns is None:
            return "timeout"
        if self.received_ns - self.sent_ns > TIMEOUT_NS:
            return "late"
        return "on_time"

    @property
    def rtt_ns(self) -> int | None:
        """Return application RTT from send completion, including late replies."""
        if self.sent_ns is None or self.received_ns is None:
            return None
        return self.received_ns - self.sent_ns

    @property
    def completion_ns(self) -> int | None:
        """Include generator delay rather than silently hiding a late send."""
        if self.received_ns is None:
            return None
        return self.received_ns - self.scheduled_ns
