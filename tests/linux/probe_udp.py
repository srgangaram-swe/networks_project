"""Small synthetic UDP probes used only on the owned namespace testbed."""

import argparse
import json
import socket
import struct
import time

CLIENT = "10.203.0.2"
SERVER = "10.203.0.6"
SIZE = 512


def send(port: int, rate: int, tos: int) -> dict:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((SERVER, port))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, tos)
        sock.settimeout(1)
        start = time.monotonic_ns()
        for sequence in range(rate):
            due = start + sequence * 1_000_000_000 // rate
            time.sleep(max(0, (due - time.monotonic_ns()) / 1e9))
            payload = b"NPQ1" + struct.pack("!I", sequence) + bytes(SIZE - 8)
            sock.sendto(payload, (CLIENT, 42001))
        return {"sent": rate, "elapsed_ns": time.monotonic_ns() - start}


def receive() -> dict:
    seen, samples, counts = set(), [], {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_RECVTOS, 1)
        sock.bind((CLIENT, 42001))
        sock.settimeout(0.1)
        print("ready", flush=True)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                payload, ancillary, flags, peer = sock.recvmsg(SIZE + 1, socket.CMSG_SPACE(1))
            except TimeoutError:
                continue
            if flags or len(payload) != SIZE or payload[:4] != b"NPQ1" or peer[0] != SERVER:
                raise ValueError("unexpected probe packet")
            sequence = struct.unpack("!I", payload[4:8])[0]
            if sequence in seen or len(seen) >= 5000:
                raise ValueError("duplicate or excessive probe packets")
            seen.add(sequence)
            tos = [
                value[0]
                for level, kind, value in ancillary
                if level == socket.IPPROTO_IP and kind == socket.IP_TOS
            ]
            if len(tos) != 1:
                raise ValueError("missing received DS field")
            key = str(tos[0])
            counts[key] = counts.get(key, 0) + 1
            if counts[key] <= 4:
                samples.append({"sequence": sequence, "tos": tos[0], "payload_bytes": SIZE})
    return {"received": len(seen), "tos_counts": counts, "packet_samples": samples}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("send", "receive"))
    parser.add_argument("--port", type=int, choices=(42000, 42002), default=42000)
    parser.add_argument("--rate", type=int, choices=(500, 5000), default=500)
    parser.add_argument("--tos", type=int, choices=(0, 184), default=0)
    args = parser.parse_args()
    result = receive() if args.role == "receive" else send(args.port, args.rate, args.tos)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
