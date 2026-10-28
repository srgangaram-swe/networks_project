"""Open-loop scheduling and reply accounting, independent of socket I/O."""

import heapq
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace

from src.experiment_config import bounded_integer
from src.foreground_wire import PayloadMismatch, decode, encode
from src.measurement_contract import (
    CONTRACT_VERSION,
    MAX_IN_FLIGHT,
    MAX_TIMESTAMP_NS,
    TIMEOUT_NS,
    RequestRecord,
)

NS_PER_SECOND = 1_000_000_000
MAX_SEND_LAG_NS = 1_000_000
MAX_EVENTS = 4096


@dataclass(frozen=True)
class Workload:
    warmup_ms: int = 10_000
    measurement_ms: int = 60_000
    drain_ms: int = 2_000
    requests_per_second: int = 500
    max_in_flight: int = MAX_IN_FLIGHT

    def __post_init__(self) -> None:
        for name, low, high in (
            ("warmup_ms", 0, 60_000),
            ("measurement_ms", 2, 120_000),
            ("drain_ms", 1001, 10_000),
            ("requests_per_second", 1, 500),
            ("max_in_flight", 1, MAX_IN_FLIGHT),
        ):
            bounded_integer(getattr(self, name), name, low, high)
        if any(
            ms * self.requests_per_second % 1000 for ms in (self.warmup_ms, self.measurement_ms)
        ):
            raise ValueError("each phase must contain an integral number of request slots")

    @property
    def warmup_count(self) -> int:
        return self.warmup_ms * self.requests_per_second // 1000

    @property
    def total_count(self) -> int:
        return (self.warmup_ms + self.measurement_ms) * self.requests_per_second // 1000


class Collector:
    """Single-threaded state machine; request history is bounded by the plan.

    Expiring a request frees its in-flight slot but retains the record. That
    separates admission control from the evidence needed for late replies.
    """

    def __init__(self, plan: Workload, start_ns: int) -> None:
        duration_ns = (plan.warmup_ms + plan.measurement_ms + plan.drain_ms) * 1_000_000
        bounded_integer(start_ns, "start_ns", 0, MAX_TIMESTAMP_NS - duration_ns - TIMEOUT_NS)
        self.plan = plan
        self.start_ns = start_ns
        self.end_ns = start_ns + duration_ns
        self.records: list[RequestRecord] = []
        self.active: set[int] = set()
        self.deadlines: list[tuple[int, int]] = []
        self.events: list[dict] = []
        self.event_counts: Counter[str] = Counter()

    @property
    def next_due_ns(self) -> int:
        if len(self.records) == self.plan.total_count:
            return self.end_ns
        return self.start_ns + len(self.records) * NS_PER_SECOND // self.plan.requests_per_second

    def event(self, kind: str, now_ns: int, request_id: int | None = None) -> None:
        self.event_counts[kind] += 1
        if len(self.events) < MAX_EVENTS:
            self.events.append({"kind": kind, "observed_ns": now_ns, "request_id": request_id})

    def advance(self, now_ns: int, send: Callable[[bytes], int]) -> None:
        """Attempt due slots; send returns the timestamp just after sendto."""
        while self.deadlines and self.deadlines[0][0] < now_ns:
            _, request_id = heapq.heappop(self.deadlines)
            self.active.discard(request_id)
        while len(self.records) < self.plan.total_count and self.next_due_ns <= now_ns:
            request_id = len(self.records)
            scheduled = self.next_due_ns
            record = RequestRecord(request_id, scheduled, None, None)
            self.records.append(record)
            if now_ns - scheduled > MAX_SEND_LAG_NS:
                self.event("generator_late", now_ns, request_id)
                continue
            if len(self.active) >= self.plan.max_in_flight:
                self.event("in_flight_limit", now_ns, request_id)
                continue
            try:
                sent_ns = send(encode(request_id, scheduled))
            except BlockingIOError:
                self.event("send_would_block", now_ns, request_id)
                continue
            except OSError:
                self.event("send_error", now_ns, request_id)
                raise
            bounded_integer(sent_ns, "sent_ns", now_ns, MAX_TIMESTAMP_NS - TIMEOUT_NS)
            self.records[request_id] = replace(record, sent_ns=sent_ns)
            self.active.add(request_id)
            heapq.heappush(self.deadlines, (sent_ns + TIMEOUT_NS, request_id))
            # Recheck the clock in the driver before another send. Missed slots
            # never become a queued burst, even after the process is suspended.
            return

    def receive(self, payload: bytes, now_ns: int) -> None:
        try:
            request_id, scheduled_ns = decode(payload)
        except PayloadMismatch:
            self.event("payload_mismatch", now_ns)
            return
        except ValueError:
            self.event("malformed_reply", now_ns)
            return
        if request_id >= len(self.records):
            self.event("unknown_request", now_ns, request_id)
            return
        record = self.records[request_id]
        if record.sent_ns is None or scheduled_ns != record.scheduled_ns:
            self.event("request_mismatch", now_ns, request_id)
        elif now_ns < record.sent_ns:
            self.event("clock_order_error", now_ns, request_id)
        elif record.received_ns is not None:
            self.event("duplicate_reply", now_ns, request_id)
        else:
            self.records[request_id] = replace(record, received_ns=now_ns)
            self.active.discard(request_id)

    def finish(self, status: str, now_ns: int) -> dict:
        """Keep every planned slot, including those left after cancellation."""
        if status not in {"completed", "cancelled", "io_error"}:
            raise ValueError("invalid collector status")
        while len(self.records) < self.plan.total_count:
            request_id, scheduled = len(self.records), self.next_due_ns
            self.records.append(RequestRecord(request_id, scheduled, None, None))
            self.event("not_attempted", now_ns, request_id)
        summaries = {}
        for phase, records in (
            ("warmup", self.records[: self.plan.warmup_count]),
            ("measurement", self.records[self.plan.warmup_count :]),
        ):
            counts = Counter(record.outcome for record in records)
            summaries[phase] = {
                key: counts[key] for key in ("on_time", "late", "timeout", "not_sent")
            }
        incomplete = sum(
            record.sent_ns is not None
            and record.received_ns is None
            and now_ns <= record.sent_ns + TIMEOUT_NS
            for record in self.records
        )
        dropped = sum(self.event_counts.values()) - len(self.events)
        return {
            "schema_version": 1,
            "protocol_status": "proposed",
            "status": status,
            "config": asdict(self.plan),
            "start_ns": self.start_ns,
            "measurement_start_ns": self.start_ns + self.plan.warmup_ms * 1_000_000,
            "measurement_end_ns": self.end_ns - self.plan.drain_ms * 1_000_000,
            "planned_end_ns": self.end_ns,
            "finished_ns": now_ns,
            "incomplete_deadlines": incomplete,
            "counts": summaries,
            "event_counts": dict(self.event_counts),
            "events_dropped": dropped,
            "events": self.events,
            "records": [
                {"schema_version": CONTRACT_VERSION, **asdict(record)} for record in self.records
            ],
        }
