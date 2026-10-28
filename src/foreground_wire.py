"""Fixed-size v1 UDP messages for an isolated request-response workload."""

import struct

from src.experiment_config import bounded_integer
from src.measurement_contract import CONTRACT_VERSION, MAX_TIMESTAMP_NS

MESSAGE_BYTES = 512
HEADER = struct.Struct("!4sIQQ")
PADDING = bytes(index % 256 for index in range(MESSAGE_BYTES - HEADER.size))


class PayloadMismatch(ValueError):
    """The header is readable, but the deterministic body was changed."""


def encode(request_id: int, scheduled_ns: int) -> bytes:
    bounded_integer(request_id, "request_id", 0, 2**64 - 1)
    bounded_integer(scheduled_ns, "scheduled_ns", 0, MAX_TIMESTAMP_NS)
    return HEADER.pack(b"NQL1", CONTRACT_VERSION, request_id, scheduled_ns) + PADDING


def decode(payload: bytes) -> tuple[int, int]:
    if len(payload) != MESSAGE_BYTES:
        raise ValueError("a foreground datagram must contain exactly 512 bytes")
    magic, version, request_id, scheduled_ns = HEADER.unpack_from(payload)
    if magic != b"NQL1" or version != CONTRACT_VERSION or scheduled_ns > MAX_TIMESTAMP_NS:
        raise ValueError("invalid foreground header")
    if payload[HEADER.size :] != PADDING:
        raise PayloadMismatch("foreground payload mismatch")
    return request_id, scheduled_ns
