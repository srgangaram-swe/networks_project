"""Bounded server state for a Birrell--Nelson-inspired RPC packet protocol."""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from .rpc_packet_protocol import Packet, PacketKind, decode_packet, encode_packet

DEFAULT_MAX_ACTIVITIES = 1024


@dataclass
class _ActivityState:
    """Retain the latest sequence and its reply until acknowledged."""

    sequence: int
    reply: bytes | None


class RpcServer:
    """Execute each new call once while retaining per-activity sequence state.

    The caller owns socket I/O. handle_packet() accepts an encoded CALL or ACK
    and returns encoded RESULT bytes, or None when no reply should be sent.
    State persists only for the lifetime of this server instance; it is not
    a durable exactly-once execution guarantee across server crashes.
    """

    def __init__(
        self,
        handler: Callable[[bytes], bytes],
        *,
        max_activities: int = DEFAULT_MAX_ACTIVITIES,
    ) -> None:
        if not callable(handler):
            raise TypeError("handler must be callable")
        if type(max_activities) is not int or not 1 <= max_activities <= 4096:
            raise ValueError("max_activities must be between 1 and 4096")

        self.handler = handler
        self.max_activities = max_activities
        self.activities: dict[tuple[int, int], _ActivityState] = {}
        self.counts: Counter[str] = Counter()

    def handle_packet(self, data: bytes) -> bytes | None:
        """Process a request, resend its cached result, or accept its ACK."""
        try:
            packet = decode_packet(data)
        except (TypeError, ValueError):
            self.counts["invalid_packets"] += 1
            return None

        key = (packet.machine_id, packet.activity_id)
        state = self.activities.get(key)

        if packet.kind == PacketKind.ACK:
            if state is None or packet.sequence != state.sequence or state.reply is None:
                self.counts["unexpected_acks"] += 1
                return None
            state.reply = None
            self.counts["results_acked"] += 1
            return None

        if packet.kind != PacketKind.CALL:
            self.counts["unexpected_packets"] += 1
            return None

        if state is not None:
            if packet.sequence < state.sequence:
                self.counts["stale_calls"] += 1
                return None
            if packet.sequence == state.sequence:
                self.counts["duplicate_calls"] += 1
                return state.reply
        elif len(self.activities) >= self.max_activities:
            # Retain sequence history rather than evicting it and allowing
            # old duplicate calls to execute again.
            self.counts["activity_limit"] += 1
            return None

        # Store state only after a valid reply has been encoded. Handler
        # exceptions propagate; the caller decides how to report failures.
        result = self.handler(packet.payload)
        if not isinstance(result, bytes):
            raise TypeError("RPC handler must return bytes")
        reply = encode_packet(
            Packet(
                PacketKind.RESULT,
                packet.machine_id,
                packet.activity_id,
                packet.sequence,
                result,
            )
        )
        self.activities[key] = _ActivityState(packet.sequence, reply)
        self.counts["calls_executed"] += 1
        return reply

    def statistics(self) -> dict[str, int]:
        """Return a snapshot of server protocol counters."""
        return dict(self.counts)
