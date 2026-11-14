"""Explicit foreground transports and version-checked Linux TCP socket counters."""

import platform
import socket
import struct


def validate_transport(value: str) -> str:
    if value not in ("udp", "tcp"):
        raise ValueError("transport must be udp or tcp")
    return value


def parse_tcp_info(data: bytes) -> dict:
    if not isinstance(data, bytes) or len(data) < 104:
        raise ValueError("Linux TCP_INFO needs at least the 104-byte base structure")
    fields = {
        "unacked_segments": 24,
        "sacked_segments": 28,
        "lost_segments": 32,
        "retransmitted_segments_in_flight": 36,
        "rtt_us": 68,
        "rtt_variation_us": 72,
        "send_cwnd_segments": 80,
        "total_retransmissions": 100,
    }
    result = {name: struct.unpack_from("=I", data, offset)[0] for name, offset in fields.items()}
    if len(data) >= 144:
        result.update(
            bytes_acked=struct.unpack_from("=Q", data, 120)[0],
            bytes_received=struct.unpack_from("=Q", data, 128)[0],
            segments_out=struct.unpack_from("=I", data, 136)[0],
            segments_in=struct.unpack_from("=I", data, 140)[0],
        )
    return {"status": "available", "source": "Linux_TCP_INFO", **result}


def tcp_info(sock: socket.socket) -> dict:
    if platform.system() != "Linux" or not hasattr(socket, "TCP_INFO"):
        return {"status": "unavailable_platform", "source": "Linux_TCP_INFO"}
    try:
        return parse_tcp_info(sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, 256))
    except OSError as error:
        return {"status": "unavailable_socket", "errno": error.errno, "source": "Linux_TCP_INFO"}
