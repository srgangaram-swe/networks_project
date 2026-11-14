"""Bounded Ethernet/IPv4/TCP header accounting for a dedicated client interface."""

import ipaddress
import struct
from collections import Counter

MAX_PACKETS = 2_000_000
MAX_FLOWS = 64


def decode_header(data: bytes):
    if len(data) < 14:
        return None
    protocol = struct.unpack_from("!H", data, 12)[0]
    offset = 14
    if protocol == 0x8100:
        if len(data) < 18:
            return None
        protocol, offset = struct.unpack_from("!H", data, 16)[0], 18
    if protocol != 0x0800 or len(data) < offset + 20:
        return None
    ip = data[offset:]
    header = (ip[0] & 15) * 4
    total, fragment = struct.unpack_from("!HH", ip, 2)[0], struct.unpack_from("!H", ip, 6)[0]
    if ip[0] >> 4 != 4 or header < 20 or ip[9] != 6 or fragment & 0x3FFF:
        return None
    if len(ip) < header + 20 or total < header + 20:
        return None
    tcp = ip[header:]
    tcp_header = (tcp[12] >> 4) * 4
    if tcp_header < 20 or len(tcp) < tcp_header or total < header + tcp_header:
        return None
    source, destination, sequence, ack = struct.unpack_from("!HHII", tcp)
    return {
        "source": str(ipaddress.IPv4Address(ip[12:16])),
        "destination": str(ipaddress.IPv4Address(ip[16:20])),
        "source_port": source,
        "destination_port": destination,
        "sequence": sequence,
        "ack": ack,
        "flags": tcp[13],
        "window": struct.unpack_from("!H", tcp, 14)[0],
        "payload_bytes": total - header - tcp_header,
    }


def ahead(left: int, right: int) -> bool:
    return 0 < (left - right) % 2**32 < 2**31


class AckObserver:
    """O(P) work for P <= 2 million packets, O(F + W) retained state.

    Counts are duplicate cumulative ACK candidates under RFC 5681's header
    conditions. They cannot identify every cause of loss or reordering.
    """

    def __init__(self, client, server, start_ns):
        self.client, self.server, self.start_ns = client, server, start_ns
        self.flows = {}
        self.windows = {}
        self.packets = 0

    def observe(self, data, observed_ns):
        self.packets += 1
        if self.packets > MAX_PACKETS:
            raise ValueError("passive TCP packet budget exceeded")
        packet = decode_header(data)
        if packet is None:
            return
        outbound = (packet["source"], packet["destination"]) == (self.client, self.server)
        inbound = (packet["source"], packet["destination"]) == (self.server, self.client)
        if not (outbound or inbound):
            return
        key = (
            (packet["source_port"], packet["destination_port"])
            if outbound
            else (packet["destination_port"], packet["source_port"])
        )
        if key not in self.flows and len(self.flows) >= MAX_FLOWS:
            raise ValueError("passive TCP flow budget exceeded")
        flow = self.flows.setdefault(
            key,
            {
                direction: {"end": None, "ack": None, "window": None}
                for direction in ("client", "server")
            },
        )
        index = (observed_ns - self.start_ns) // 1_000_000_000
        if not 0 <= index <= 190:
            raise ValueError("passive TCP observation outside its time budget")
        counts = self.windows.setdefault(index, Counter())
        scope = "foreground" if key == (42001, 42000) else "bulk"
        counts[f"{scope}_packets"] += 1
        self._sent(flow["client" if outbound else "server"], packet, counts, scope)
        self._acked(flow["server" if outbound else "client"], packet, counts, scope)

    @staticmethod
    def _sent(state, packet, counts, scope):
        size = packet["payload_bytes"] + bool(packet["flags"] & 2) + bool(packet["flags"] & 1)
        if not size:
            return
        end = (packet["sequence"] + size) % 2**32
        if state["end"] is not None and not ahead(end, state["end"]):
            counts[f"{scope}_repeated_sequence_candidates"] += 1
        if state["end"] is None or ahead(end, state["end"]):
            state["end"] = end

    @staticmethod
    def _acked(state, packet, counts, scope):
        if not packet["flags"] & 16:
            return
        counts[f"{scope}_acks"] += 1
        pure = packet["payload_bytes"] == 0 and not packet["flags"] & 7
        outstanding = state["end"] is not None and ahead(state["end"], packet["ack"])
        if (
            pure
            and outstanding
            and (packet["ack"], packet["window"]) == (state["ack"], state["window"])
        ):
            counts[f"{scope}_duplicate_ack_candidates"] += 1
        state.update(ack=packet["ack"], window=packet["window"])

    def report(self):
        return {
            "schema_version": 1,
            "scope": "client_interface_bidirectional_ipv4_tcp_headers",
            "interpretation": "duplicate_ACK_and_repeated_sequence_candidates_not_packet_loss",
            "observed_packets": self.packets,
            "observed_flows": len(self.flows),
            "clock": "client_processing_monotonic_ns",
            "start_ns": self.start_ns,
            "windows": [
                {"index": index, **dict(counts)} for index, counts in sorted(self.windows.items())
            ],
        }
