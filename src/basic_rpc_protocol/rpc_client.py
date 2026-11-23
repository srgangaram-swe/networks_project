"""Bounded client state for a Birrell--Nelson-inspired RPC packet protocol."""

from collections import Counter
from dataclasses import dataclass

from .rpc_packet_protocol import Packet, PacketKind, encode_packet, decode_packet

DEFAULT_TIMEOUT_NS = 1_000_000_000
DEFAULT_MAX_RETRIES = 3
MAX_TIMESTAMP_NS = 2**63 - 1


class RpcTimeout(TimeoutError):
    """A call received no matching result after its retry budget expired."""


@dataclass
class _PendingCall:
    """One in-flight call; retransmissions reuse the original packet bytes."""

    sequence: int
    request: bytes
    deadline_ns: int
    retries: int = 0


class RpcClient:
    """One outstanding call per activity, with explicit timer-driven retries.

    The caller owns socket I/O and passes monotonic nanosecond timestamps.
    start_call() and retry_due() return packets to send. handle_packet()
    returns an ACK to send when a matching RESULT arrives.
    """

    def __init__(
            self,
            machine_id: int,
            activity_id: int,
            *,
            timeout_ns: int = DEFAULT_TIMEOUT_NS,
            max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        # The encoder checks the exact integer types and identifier ranges.
        encode_packet(Packet(PacketKind.ACK, machine_id, activity_id, 0))
        if type(timeout_ns) is not int or not 1_000_000 <= timeout_ns <= 60_000_000_000:
            raise ValueError("timeout_ns must be between 1 ms and 60 seconds")
        if type(max_retries) is not int or not 0 <= max_retries <= 20:
            raise ValueError("max_retries must be between 0 and 20")

        self.machine_id = machine_id
        self.activity_id = activity_id
        self.timeout_ns = timeout_ns
        self.max_retries = max_retries
        self.sequence = 0
        self._pending: _PendingCall | None = None
        self._result: bytes | None = None
        self._last_ack: bytes | None = None
        self._last_completed_sequence: int | None = None
        self._last_now_ns = 0
        self.counts: Counter[str] = Counter()

    def _check_time(self, now_ns: int) -> None:
        if (
                type(now_ns) is not int
                or not self._last_now_ns <= now_ns <= MAX_TIMESTAMP_NS - self.timeout_ns
        ):
            raise ValueError("timestamp must be nondecreasing and leave room for a timeout")
        self._last_now_ns = now_ns

    @property
    def has_pending_call(self) -> bool:
        return self._pending is not None

    @property
    def next_deadline_ns(self) -> int | None:
        return None if self._pending is None else self._pending.deadline_ns

    def start_call(self, payload: bytes, now_ns: int) -> bytes:
        """Start a call and return its CALL packet for transmission."""
        self._check_time(now_ns)
        if self._pending is not None:
            raise RuntimeError("this activity already has an outstanding call")
        if self._result is not None:
            raise RuntimeError("consume the previous result before starting another call")
        if self.sequence == 2**64 - 1:
            raise OverflowError("RPC sequence space exhausted")

        sequence = self.sequence + 1
        request = encode_packet(Packet(PacketKind.CALL, self.machine_id, self.activity_id, sequence, payload))
        self.sequence = sequence
        self._pending = _PendingCall(sequence, request, now_ns + self.timeout_ns)
        self.counts["calls_started"] += 1
        return request

    def retry_due(self, now_ns: int) -> bytes | None:
        """Return the original CALL when due, or raise after the final timeout."""
        self._check_time(now_ns)
        pending = self._pending
        if pending is None or now_ns < pending.deadline_ns:
            return None
        if pending.retries >= self.max_retries:
            self._pending = None
            self.counts["calls_timed_out"] += 1
            raise RpcTimeout(f"RPC call {pending.sequence} exhausted its retry budget")

        pending.retries += 1
        pending.deadline_ns = now_ns + self.timeout_ns
        self.counts["retransmissions"] += 1
        return pending.request

    def handle_packet(self, data: bytes, now_ns: int) -> bytes | None:
        """Accept a matching RESULT and return an ACK packet to transmit.

        Invalid or unrelated packets are ignored and counted. Duplicate
        results for the latest completed call are acknowledged again.
        """
        self._check_time(now_ns)
        try:
            packet = decode_packet(data)
        except (TypeError, ValueError):
            self.counts["invalid_packets"] += 1
            return None

        if (packet.kind != PacketKind.RESULT or packet.machine_id != self.machine_id or packet.activity_id != self.activity_id):
            self.counts["unexpected_packets"] += 1
            return None

        pending = self._pending
        if pending is not None and packet.sequence == pending.sequence:
            self._result = packet.payload
            self._pending = None
            self._last_completed_sequence = packet.sequence
            self._last_ack = encode_packet(Packet(PacketKind.ACK, self.machine_id, self.activity_id, packet.sequence))
            self.counts["calls_completed"] += 1
            return self._last_ack

        if packet.sequence == self._last_completed_sequence:
            self.counts["duplicate_results"] += 1
            return self._last_ack

        self.counts["unexpected_packets"] += 1
        return None

    def take_result(self) -> bytes:
        """Consume the result of the most recently completed call."""
        if self._result is None:
            raise RuntimeError("no completed RPC result is available")
        result = self._result
        self._result = None
        return result

    def statistics(self) -> dict[str, int]:
        """Return a snapshot of client protocol counters."""
        return dict(self.counts)
