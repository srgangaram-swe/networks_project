"""Bounded 512-byte TCP framing with the same application request accounting as UDP."""

import errno
import select
import selectors
import socket
import time
from collections import Counter
from threading import Event

from src.experiment_config import bounded_integer
from src.foreground import Collector, Workload
from src.foreground_io import POLL_SECONDS, ReplyBudget, _poll_timeout, endpoint
from src.foreground_wire import MESSAGE_BYTES, decode
from src.transport import tcp_info


def send_frame(sock: socket.socket, payload: bytes, stop: Event) -> int:
    sent = sock.send(payload)
    if not sent:
        raise ConnectionResetError("TCP stream closed while sending a frame")
    deadline = time.monotonic() + 0.1
    while sent < len(payload):
        if stop.is_set():
            raise InterruptedError("TCP send cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(errno.ETIMEDOUT, "partial TCP frame exceeded its send deadline")
        if select.select([], [sock], [], min(POLL_SECONDS, remaining))[1]:
            try:
                count = sock.send(payload[sent:])
            except BlockingIOError:
                continue
            if count == 0:
                raise ConnectionResetError("TCP stream closed after a partial frame")
            sent += count
    return time.monotonic_ns()


def _receive(sock, buffer, collector):
    try:
        data = sock.recv(32 * MESSAGE_BYTES)
    except BlockingIOError:
        return
    if not data:
        raise ConnectionResetError("TCP responder closed before the measurement ended")
    buffer.extend(data)
    complete = len(buffer) // MESSAGE_BYTES
    for index in range(complete):
        offset = index * MESSAGE_BYTES
        collector.receive(bytes(buffer[offset : offset + MESSAGE_BYTES]), time.monotonic_ns())
    del buffer[: complete * MESSAGE_BYTES]


def run_client(
    plan: Workload, bind, peer, *, allow_isolated=False, stop=None, start_ns=None, observe=None
):
    bind, peer = endpoint(*bind, allow_isolated), endpoint(*peer, allow_isolated)
    if not peer[1] or bind == peer:
        raise ValueError("TCP responder needs a distinct endpoint and explicit port")
    stop = stop if stop is not None else Event()
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        selectors.DefaultSelector() as poll,
    ):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.bind(bind)
        sock.settimeout(2)
        sock.connect(peer)
        sock.setblocking(False)
        poll.register(sock, selectors.EVENT_READ)
        start = time.monotonic_ns() + 20_000_000 if start_ns is None else start_ns
        collector = Collector(plan, start, observe=observe)
        before = tcp_info(sock)
        buffer, samples = bytearray(), []
        next_sample = start
        status, failure_errno = "completed", None
        cpu_start = time.process_time_ns()
        try:
            while time.monotonic_ns() < collector.end_ns:
                if stop.is_set():
                    status = "cancelled"
                    break
                now = time.monotonic_ns()
                collector.advance(now, lambda data: send_frame(sock, data, stop))
                if now >= next_sample:
                    samples.append({"observed_ns": now, **tcp_info(sock)})
                    next_sample = now + 1_000_000_000
                if poll.select(_poll_timeout(collector)):
                    _receive(sock, buffer, collector)
        except OSError as error:
            status = "cancelled" if stop.is_set() else "io_error"
            failure_errno = error.errno
            collector.event("socket_error", time.monotonic_ns())
        result = collector.finish(status, time.monotonic_ns())
        result.update(
            client_process_cpu_ns=time.process_time_ns() - cpu_start,
            socket_error_errno=failure_errno,
            bind=sock.getsockname(),
            peer=peer,
            clock_resolution_seconds=time.get_clock_info("monotonic").resolution,
            transport_metrics={
                "transport": "tcp",
                "before": before,
                "after": tcp_info(sock),
                "samples": samples,
                "framing_bytes": MESSAGE_BYTES,
                "nagle_disabled": True,
            },
        )
        return result


def _session(connection, stop, end, counts):
    connection.settimeout(POLL_SECONDS)
    connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    buffer = bytearray()
    budget = ReplyBudget(time.monotonic_ns())
    while time.monotonic_ns() < end and not stop.is_set():
        try:
            data = connection.recv(MESSAGE_BYTES - len(buffer))
        except TimeoutError:
            continue
        if not data:
            return
        buffer.extend(data)
        if len(buffer) == MESSAGE_BYTES:
            counts["received"] += 1
            try:
                decode(bytes(buffer))
            except ValueError:
                counts["malformed_request"] += 1
                buffer.clear()
                continue
            if budget.allow(time.monotonic_ns()):
                send_frame(connection, bytes(buffer), stop)
                counts["echoed"] += 1
            else:
                counts["rate_limited"] += 1
            buffer.clear()


def run_responder(
    bind, peer_address, *, duration_ms=90000, allow_isolated=False, stop=None, ready=None
):
    bind = endpoint(*bind, allow_isolated)
    expected = endpoint(peer_address, 0, allow_isolated)[0]
    bounded_integer(duration_ms, "duration_ms", 1, 200000)
    stop = stop if stop is not None else Event()
    counts = Counter()
    status, failure_errno = "completed", None
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(bind)
        listener.listen(1)
        listener.settimeout(POLL_SECONDS)
        end = time.monotonic_ns() + duration_ms * 1_000_000
        if ready is not None:
            ready(listener.getsockname())
        try:
            while time.monotonic_ns() < end and not stop.is_set():
                try:
                    connection, peer = listener.accept()
                except TimeoutError:
                    continue
                with connection:
                    if peer[0] != expected:
                        counts["wrong_peer"] += 1
                        continue
                    _session(connection, stop, end, counts)
        except OSError as error:
            status, failure_errno = "io_error", error.errno
        if stop.is_set() and status == "completed":
            status = "cancelled"
        return {
            "status": status,
            "counts": dict(counts),
            "bind": listener.getsockname(),
            "socket_error_errno": failure_errno,
        }
