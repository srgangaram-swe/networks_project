"""Bounded UDP endpoints. No routes, interfaces, or queue policies are changed."""

import ipaddress
import selectors
import socket
import time
from collections import Counter
from collections.abc import Callable
from threading import Event

from src.experiment_config import bounded_integer
from src.foreground import Collector, Workload
from src.foreground_wire import MESSAGE_BYTES, PayloadMismatch, decode

POLL_SECONDS = 0.05
PACING_POLL_SECONDS = 0.0005
RECEIVE_BATCH = 32
PRIVATE_NETWORKS = tuple(
    ipaddress.IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


class ReplyBudget:
    """Limit validation and echoes to 1000 packets/s with a 32-packet burst."""

    def __init__(self, now_ns: int) -> None:
        self.updated_ns = now_ns
        self.credit_ns = 32_000_000

    def allow(self, now_ns: int) -> bool:
        if now_ns < self.updated_ns:
            raise ValueError("the rate-budget clock moved backwards")
        self.credit_ns = min(32_000_000, self.credit_ns + now_ns - self.updated_ns)
        self.updated_ns = now_ns
        if self.credit_ns < 1_000_000:
            return False
        self.credit_ns -= 1_000_000
        return True


def endpoint(address: str, port: int, allow_isolated: bool = False) -> tuple[str, int]:
    """Permit loopback by default; private addresses require explicit opt-in."""
    if not isinstance(address, str) or type(allow_isolated) is not bool:
        raise ValueError("provide a literal IPv4 string and a boolean isolation flag")
    ip = ipaddress.IPv4Address(address)
    if not ip.is_loopback and not (allow_isolated and any(ip in net for net in PRIVATE_NETWORKS)):
        raise ValueError("use loopback or an explicitly authorized private testbed address")
    bounded_integer(port, "port", 0, 65535)
    if 0 < port < 1024:
        raise ValueError("privileged ports are not supported")
    return str(ip), port


def run_client(
    plan: Workload,
    bind: tuple[str, int],
    peer: tuple[str, int],
    *,
    allow_isolated: bool = False,
    stop: Event | None = None,
) -> dict:
    bind = endpoint(*bind, allow_isolated)
    peer = endpoint(*peer, allow_isolated)
    if not peer[1] or bind == peer:
        raise ValueError("the responder needs a nonzero port and a distinct endpoint")
    stop = stop if stop is not None else Event()
    status = "completed"
    failure_errno = None
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock,
        selectors.DefaultSelector() as poll,
    ):
        sock.bind(bind)
        sock.setblocking(False)
        poll.register(sock, selectors.EVENT_READ)
        collector = Collector(plan, time.monotonic_ns() + 20_000_000)
        cpu_start = time.process_time_ns()

        def send(payload: bytes) -> int:
            count = sock.sendto(payload, peer)
            sent_ns = time.monotonic_ns()
            if count != len(payload):
                raise OSError("incomplete datagram send")
            return sent_ns

        try:
            while time.monotonic_ns() < collector.end_ns:
                if stop.is_set():
                    status = "cancelled"
                    break
                collector.advance(time.monotonic_ns(), send)
                timeout = max(0, (collector.next_due_ns - time.monotonic_ns()) / 1e9)
                if len(collector.records) < plan.total_count:
                    # Short waits near a send slot reduce timer coalescing on
                    # general-purpose kernels without a busy-spin loop.
                    timeout = (
                        min(PACING_POLL_SECONDS, timeout) if timeout <= 0.005 else timeout - 0.005
                    )
                if not poll.select(min(POLL_SECONDS, timeout)):
                    continue
                # A bounded batch prevents unsolicited traffic from starving
                # the next send deadline or the cancellation check.
                for _ in range(RECEIVE_BATCH):
                    try:
                        payload, source = sock.recvfrom(MESSAGE_BYTES + 1)
                    except BlockingIOError:
                        break
                    received_ns = time.monotonic_ns()
                    if received_ns >= collector.end_ns:
                        break
                    if source != peer:
                        collector.event("wrong_peer", received_ns)
                    else:
                        collector.receive(payload, received_ns)
        except OSError as exc:
            status = "io_error"
            failure_errno = exc.errno
            collector.event("socket_error", time.monotonic_ns())
        cpu_used = time.process_time_ns() - cpu_start
        result = collector.finish(status, time.monotonic_ns())
        result["client_process_cpu_ns"] = cpu_used
        result["socket_error_errno"] = failure_errno
        result["bind"] = sock.getsockname()
        result["peer"] = peer
        result["clock_resolution_seconds"] = time.get_clock_info("monotonic").resolution
        return result


def run_responder(
    bind: tuple[str, int],
    peer_address: str,
    *,
    duration_ms: int = 90_000,
    allow_isolated: bool = False,
    stop: Event | None = None,
    ready: Callable[[tuple[str, int]], None] | None = None,
) -> dict:
    """Echo valid messages from one source address, with bounded rate and lifetime."""
    bind = endpoint(*bind, allow_isolated)
    peer_address = endpoint(peer_address, 0, allow_isolated)[0]
    bounded_integer(duration_ms, "duration_ms", 1, 200_000)
    stop = stop if stop is not None else Event()
    counts: Counter[str] = Counter()
    status = "completed"
    failure_errno = None
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock,
        selectors.DefaultSelector() as poll,
    ):
        sock.bind(bind)
        sock.setblocking(False)
        poll.register(sock, selectors.EVENT_READ)
        start = time.monotonic_ns()
        end = start + duration_ms * 1_000_000
        budget = ReplyBudget(start)
        if ready is not None:
            ready(sock.getsockname())
        try:
            while time.monotonic_ns() < end and not stop.is_set():
                if not poll.select(min(POLL_SECONDS, max(0, (end - time.monotonic_ns()) / 1e9))):
                    continue
                try:
                    payload, source = sock.recvfrom(MESSAGE_BYTES + 1)
                except BlockingIOError:
                    continue
                now = time.monotonic_ns()
                if now >= end:
                    break
                counts["received"] += 1
                if source[0] != peer_address:
                    counts["wrong_peer"] += 1
                    continue
                if not budget.allow(now):
                    counts["rate_limited"] += 1
                    continue
                try:
                    decode(payload)
                except PayloadMismatch:
                    counts["payload_mismatch"] += 1
                    continue
                except ValueError:
                    counts["malformed_request"] += 1
                    continue
                try:
                    if sock.sendto(payload, source) != MESSAGE_BYTES:
                        raise OSError("incomplete datagram send")
                    counts["echoed"] += 1
                except BlockingIOError:
                    counts["send_would_block"] += 1
        except OSError as exc:
            status = "io_error"
            failure_errno = exc.errno
            counts["socket_error"] += 1
        if stop.is_set() and status == "completed":
            status = "cancelled"
        return {
            "status": status,
            "counts": dict(counts),
            "bind": sock.getsockname(),
            "socket_error_errno": failure_errno,
        }
