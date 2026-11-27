"""Bounded packet encoding for a Birrell--Nelson-inspired RPC protocol."""

import struct
from dataclasses import dataclass
from enum import IntEnum

MAGIC = b"BRPC"
VERSION = 1
MAX_PACKET_BYTES = 512

# Experimental wire format, not a reproduction of Cedar RPC packets.
# Socket I/O, retransmission, and duplicate suppression belong elsewhere.
# Header: magic, version, kind, reserved, machine ID, activity ID,
# sequence number, and payload length (30 bytes total).
HEADER = struct.Struct("!4sBBHQIQH")
MAX_PAYLOAD_BYTES = MAX_PACKET_BYTES - HEADER.size


class PacketKind(IntEnum):
    """Types of messages exchanged by the RPC client and server."""

    CALL = 1
    RESULT = 2
    ACK = 3


@dataclass(frozen=True)
class Packet:
    """One RPC packet identified by machine, activity, and call sequence."""

    kind: PacketKind
    machine_id: int
    activity_id: int
    sequence: int
    payload: bytes = b""


def _check_integer(value: int, name: str, upper: int) -> None:
    if type(value) is not int or not 0 <= value <= upper:
        raise ValueError(f"{name} must be an integer between 0 and {upper}")


def encode_packet(packet: Packet) -> bytes:
    """Encode a packet without exceeding the 512-byte datagram budget."""
    if not isinstance(packet, Packet):
        raise TypeError("packet must be a Packet")
    if not isinstance(packet.kind, PacketKind):
        raise ValueError("unsupported packet kind")
    _check_integer(packet.machine_id, "machine_id", 2**64 - 1)
    _check_integer(packet.activity_id, "activity_id", 2**32 - 1)
    _check_integer(packet.sequence, "sequence", 2**64 - 1)
    if not isinstance(packet.payload, bytes) or len(packet.payload) > MAX_PAYLOAD_BYTES:
        raise ValueError(f"payload must contain at most {MAX_PAYLOAD_BYTES} bytes")
    if packet.kind == PacketKind.ACK and packet.payload:
        raise ValueError("ACK packets must not contain a payload")

    return (
        HEADER.pack(
            MAGIC,
            VERSION,
            packet.kind.value,
            0,
            packet.machine_id,
            packet.activity_id,
            packet.sequence,
            len(packet.payload),
        )
        + packet.payload
    )


def decode_packet(data: bytes) -> Packet:
    """Decode a packet and reject malformed headers or payload lengths."""
    if not isinstance(data, bytes) or not HEADER.size <= len(data) <= MAX_PACKET_BYTES:
        raise ValueError("invalid RPC packet size")

    magic, version, kind, reserved, machine_id, activity_id, sequence, length = HEADER.unpack_from(
        data
    )
    if magic != MAGIC or version != VERSION or reserved != 0:
        raise ValueError("invalid RPC packet header")

    try:
        packet_kind = PacketKind(kind)
    except ValueError as exc:
        raise ValueError("unknown RPC packet kind") from exc

    if len(data) != HEADER.size + length:
        raise ValueError("RPC packet payload length mismatch")

    packet = Packet(packet_kind, machine_id, activity_id, sequence, data[HEADER.size :])
    if packet.kind == PacketKind.ACK and packet.payload:
        raise ValueError("ACK packets must not contain a payload")
    return packet
