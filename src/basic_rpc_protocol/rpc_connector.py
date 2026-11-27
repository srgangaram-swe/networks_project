"""Bounded UDP endpoints for the experimental RPC packet protocol."""

import selectors
import socket
import time
from collections import Counter
from collections.abc import Callable
from threading import Event

from src.experiment_config import bounded_integer
from src.foreground_io import endpoint

from .rpc_client import RpcClient
from .rpc_packet_protocol import MAX_PACKET_BYTES
from .rpc_server import RpcServer

POLL_SECONDS = 0.05
RECEIVE_BATCH = 32
DEFAULT_DURATION_MS = 90_000
DEFAULT_CALL_TIMEOUT_MS = 10_000
MAX_SERVER_PACKETS = 200_000


def _send(sock: socket.socket, payload: bytes, peer: tuple[str, int]) -> None:
    """Send a complete datagram or report an I/O failure."""
    if sock.sendto(payload, peer) != len(payload):
        raise OSError("incomplete RPC datagram send")


def run_client(
    client: RpcClient,
    payload: bytes,
    bind: tuple[str, int],
    peer: tuple[str, int],
    *,
    allow_isolated: bool = False,
    stop: Event | None = None,
    total_timeout_ms: int = DEFAULT_CALL_TIMEOUT_MS,
) -> bytes:
    """Execute one RPC call, driving retries and acknowledgments over UDP.

    The RpcClient state machine owns retry decisions; this function owns only
    socket I/O and an independent upper bound on the call's total duration.
    """
    if not isinstance(client, RpcClient):
        raise TypeError("client must be an RpcClient")
    bounded_integer(total_timeout_ms, "total_timeout_ms", 1, 200_000)
    bind = endpoint(*bind, allow_isolated)
    peer = endpoint(*peer, allow_isolated)
    if peer[1] == 0 or bind == peer:
        raise ValueError("RPC server requires a nonzero port and a distinct endpoint")
    stop = stop if stop is not None else Event()

    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock,
        selectors.DefaultSelector() as poll,
    ):
        sock.bind(bind)
        sock.setblocking(False)
        poll.register(sock, selectors.EVENT_READ)
        start = time.monotonic_ns()
        deadline = start + total_timeout_ms * 1_000_000
        _send(sock, client.start_call(payload, start), peer)

        while True:
            if stop.is_set():
                raise InterruptedError("RPC call cancelled")
            now = time.monotonic_ns()
            if now >= deadline:
                raise TimeoutError("RPC call exceeded its total deadline")

            request = client.retry_due(now)
            if request is not None:
                _send(sock, request, peer)

            next_deadline = client.next_deadline_ns
            if next_deadline is None:
                raise RuntimeError("RPC client has no outstanding call")
            wait = min(POLL_SECONDS, (deadline - now) / 1e9, max(0, (next_deadline - now) / 1e9))
            if not poll.select(wait):
                continue

            if _receive_result(sock, client, peer):
                return client.take_result()


def _receive_result(sock, client, peer):
    """Acknowledge duplicates without completing a different pending call."""
    for _ in range(RECEIVE_BATCH):
        try:
            data, source = sock.recvfrom(MAX_PACKET_BYTES + 1)
        except BlockingIOError:
            break
        if source != peer:
            client.counts["wrong_peer"] += 1
            continue
        ack = client.handle_packet(data, time.monotonic_ns())
        if ack is not None:
            _send(sock, ack, peer)
            if not client.has_pending_call:
                return True
    return False


def run_server(
    server: RpcServer,
    bind: tuple[str, int],
    peer_address: str,
    *,
    duration_ms: int = DEFAULT_DURATION_MS,
    allow_isolated: bool = False,
    stop: Event | None = None,
    ready: Callable[[tuple[str, int]], None] | None = None,
) -> dict:
    """Serve RPC packets from one authorized source address for a bounded time.

    One server instance processes calls sequentially. Its duplicate-suppression
    state is in memory and does not survive a server crash or restart.
    """
    if not isinstance(server, RpcServer):
        raise TypeError("server must be an RpcServer")
    bounded_integer(duration_ms, "duration_ms", 1, 200_000)
    bind = endpoint(*bind, allow_isolated)
    peer_address = endpoint(peer_address, 0, allow_isolated)[0]
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
        end = time.monotonic_ns() + duration_ms * 1_000_000
        if ready is not None:
            ready(sock.getsockname())

        try:
            while time.monotonic_ns() < end:
                if stop.is_set():
                    status = "cancelled"
                    break
                if counts["received"] >= MAX_SERVER_PACKETS:
                    status = "packet_limit"
                    break
                remaining = max(0, (end - time.monotonic_ns()) / 1e9)
                if not poll.select(min(POLL_SECONDS, remaining)):
                    continue
                _serve_packet(sock, server, peer_address, counts)
        except OSError as exc:
            status = "io_error"
            failure_errno = exc.errno
            counts["socket_error"] += 1

        return {
            "status": status,
            "counts": dict(counts),
            "protocol_counts": server.statistics(),
            "bind": sock.getsockname(),
            "socket_error_errno": failure_errno,
        }


def _serve_packet(sock, server, peer_address, counts):
    """Process one bounded datagram from the authorized address."""
    try:
        data, source = sock.recvfrom(MAX_PACKET_BYTES + 1)
    except BlockingIOError:
        return
    counts["received"] += 1
    if source[0] != peer_address:
        counts["wrong_peer"] += 1
        return
    reply = server.handle_packet(data)
    if reply is not None:
        try:
            _send(sock, reply, source)
            counts["replies_sent"] += 1
        except BlockingIOError:
            counts["send_would_block"] += 1
