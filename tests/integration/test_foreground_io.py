import json
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from queue import Queue
from threading import Event
from unittest.mock import patch

from scripts.foreground import save_result
from src.foreground import Collector, Workload
from src.foreground_io import run_client, run_responder
from src.foreground_wire import encode
from src.measurement_contract import RequestRecord

ROOT = Path(__file__).resolve().parents[2]
REAL_SOCKET = socket.socket


@contextmanager
def responder(**kwargs):
    ready, stop = Queue(maxsize=1), Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            run_responder,
            ("127.0.0.1", 0),
            "127.0.0.1",
            stop=stop,
            ready=ready.put,
            duration_ms=4000,
            **kwargs,
        )
        try:
            yield ready.get(timeout=2), future
        finally:
            stop.set()
            future.result(timeout=2)


@contextmanager
def fault_peer():
    """Use real UDP replies to exercise corruption, duplicates, loss, and peer checks."""
    stop = Event()
    with (
        REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM) as server,
        REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM) as stranger,
    ):
        server.bind(("127.0.0.1", 0))
        stranger.bind(("127.0.0.1", 0))
        server.settimeout(0.05)

        def respond():
            deadline = time.monotonic() + 4
            index = 0
            while time.monotonic() < deadline and not stop.is_set():
                try:
                    data, source = server.recvfrom(513)
                except TimeoutError:
                    continue
                if index % 2 == 0:
                    stranger.sendto(data, source)
                    server.sendto(b"short", source)
                    server.sendto(data + b"oversized", source)
                    server.sendto(data[:-1] + bytes([data[-1] ^ 1]), source)
                    server.sendto(data, source)
                    server.sendto(data, source)
                index += 1

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(respond)
            try:
                yield server.getsockname()
            finally:
                stop.set()
                future.result(timeout=2)


class ForegroundIoTests(unittest.TestCase):
    def test_real_echo_primary_rate_and_phase_records(self):
        with responder() as (peer, future):
            result = run_client(
                Workload(warmup_ms=20, measurement_ms=200, drain_ms=1001), ("127.0.0.1", 0), peer
            )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["records"]), 110)
        self.assertGreater(result["counts"]["measurement"]["on_time"], 0)
        self.assertEqual(sum(result["counts"]["warmup"].values()), 10)
        self.assertEqual(sum(result["counts"]["measurement"].values()), 100)
        self.assertEqual(result["incomplete_deadlines"], 0)
        self.assertGreater(future.result()["counts"]["echoed"], 0)
        self.assertGreater(result["client_process_cpu_ns"], 0)
        for record in result["records"]:
            RequestRecord.from_mapping(record)

    def test_faults_are_counted_without_replacing_good_replies(self):
        with fault_peer() as peer:
            result = run_client(
                Workload(warmup_ms=0, measurement_ms=200, drain_ms=1001, requests_per_second=100),
                ("127.0.0.1", 0),
                peer,
            )
        self.assertGreater(result["counts"]["measurement"]["on_time"], 0)
        self.assertGreater(result["counts"]["measurement"]["timeout"], 0)
        for name in ("wrong_peer", "malformed_reply", "payload_mismatch", "duplicate_reply"):
            self.assertGreater(result["event_counts"][name], 0)
        self.assertEqual(len(result["records"]), 20)

    def test_real_socket_stall_does_not_erase_scheduled_slots(self):
        class StalledCollector(Collector):
            stalled = False

            def advance(self, now_ns, send):
                if not self.stalled and now_ns >= self.start_ns:
                    self.stalled = True
                    Event().wait(0.03)  # Deliberately suspend the generator, not test coordination.
                    now_ns = time.monotonic_ns()
                super().advance(now_ns, send)

        with responder() as (peer, _), patch("src.foreground_io.Collector", StalledCollector):
            result = run_client(
                Workload(warmup_ms=0, measurement_ms=200, drain_ms=1001), ("127.0.0.1", 0), peer
            )
        self.assertEqual(len(result["records"]), 100)
        self.assertGreater(result["event_counts"]["generator_late"], 0)
        self.assertGreater(result["counts"]["measurement"]["on_time"], 0)

    def test_cancel_keeps_unsent_slots_and_closes_socket(self):
        stop = Event()
        stop.set()
        with REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM) as peer:
            peer.bind(("127.0.0.1", 0))
            result = run_client(
                Workload(warmup_ms=0, measurement_ms=100),
                ("127.0.0.1", 0),
                peer.getsockname(),
                stop=stop,
            )
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["counts"]["measurement"]["not_sent"], 50)
        with REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM) as reused:
            reused.bind(result["bind"])

    def test_midstream_cancel_retains_incomplete_deadline(self):
        stop = Event()
        with (
            REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM) as peer,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            peer.bind(("127.0.0.1", 0))
            peer.settimeout(2)
            future = pool.submit(
                run_client,
                Workload(warmup_ms=0, measurement_ms=1000),
                ("127.0.0.1", 0),
                peer.getsockname(),
                stop=stop,
            )
            try:
                peer.recvfrom(513)
            finally:
                stop.set()
            result = future.result(timeout=2)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(len(result["records"]), 500)
        self.assertGreater(result["incomplete_deadlines"], 0)

    def test_reply_after_timeout_is_retained_during_drain(self):
        with (
            REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM) as peer,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            peer.bind(("127.0.0.1", 0))
            peer.settimeout(2)
            future = pool.submit(
                run_client,
                Workload(warmup_ms=0, measurement_ms=100),
                ("127.0.0.1", 0),
                peer.getsockname(),
            )
            payload, source = peer.recvfrom(513)
            Event().wait(1.05)  # Inject a reply beyond the fixed one-second deadline.
            peer.sendto(payload, source)
            peer.sendto(payload, source)
            result = future.result(timeout=3)
        self.assertEqual(result["counts"]["measurement"]["late"], 1)
        self.assertEqual(result["event_counts"]["duplicate_reply"], 1)
        record = next(r for r in result["records"] if r["received_ns"] is not None)
        self.assertGreater(record["received_ns"] - record["sent_ns"], 1_000_000_000)

    def test_partial_datagram_send_is_a_failure(self):
        class ShortSend(REAL_SOCKET):
            def sendto(self, payload, target):
                return 0

        with patch("src.foreground_io.socket.socket", ShortSend):
            result = run_client(
                Workload(warmup_ms=0, measurement_ms=100), ("127.0.0.1", 0), ("127.0.0.1", 42000)
            )
        self.assertEqual(result["status"], "io_error")
        self.assertEqual(result["counts"]["measurement"]["not_sent"], 50)

    def test_responder_backpressure_does_not_queue_retries(self):
        attempted = Event()

        class BlockedSend(REAL_SOCKET):
            def sendto(self, payload, target):
                attempted.set()
                raise BlockingIOError()

        with REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM) as client:
            with (
                patch("src.foreground_io.socket.socket", BlockedSend),
                responder() as (peer, future),
            ):
                client.sendto(encode(0, 0), peer)
                self.assertTrue(attempted.wait(2))
        self.assertEqual(future.result()["counts"]["send_would_block"], 1)

    def test_sender_error_retains_failure_and_future_slots(self):
        class FailedSend(REAL_SOCKET):
            def sendto(self, payload, target):
                raise OSError("injected send failure")

        with patch("src.foreground_io.socket.socket", FailedSend):
            result = run_client(
                Workload(warmup_ms=0, measurement_ms=100), ("127.0.0.1", 0), ("127.0.0.1", 42000)
            )
        self.assertEqual(result["status"], "io_error")
        self.assertEqual(result["event_counts"]["send_error"], 1)
        self.assertEqual(result["event_counts"]["socket_error"], 1)
        self.assertEqual(len(result["records"]), 50)

    def test_invalid_peers_and_occupied_ports_fail_without_fallback(self):
        for peer in (("127.0.0.1", 0), ("127.0.0.1", 42000)):
            with self.assertRaises(ValueError):
                run_client(Workload(), ("127.0.0.1", 42000), peer)
        with REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM) as occupied:
            occupied.bind(("127.0.0.1", 0))
            with self.assertRaises(OSError):
                run_responder(occupied.getsockname(), "127.0.0.1", duration_ms=1)

    def test_responder_rejects_malformed_and_changed_payload(self):
        with (
            responder() as (peer, future),
            REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM) as client,
        ):
            client.bind(("127.0.0.1", 0))
            client.settimeout(2)
            good = encode(7, 101)
            client.sendto(b"bad", peer)
            client.sendto(good[:-1] + bytes([good[-1] ^ 1]), peer)
            client.sendto(good, peer)
            self.assertEqual(client.recvfrom(513)[0], good)
        counts = future.result()["counts"]
        self.assertEqual(counts["malformed_request"], 1)
        self.assertEqual(counts["payload_mismatch"], 1)
        self.assertEqual(counts["echoed"], 1)

    def test_responder_wrong_source_and_natural_timeout(self):
        ready = Queue(maxsize=1)
        with (
            ThreadPoolExecutor(max_workers=1) as pool,
            REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM) as client,
        ):
            client.bind(("127.0.0.1", 0))
            future = pool.submit(
                run_responder, ("127.0.0.1", 0), "127.0.0.2", duration_ms=100, ready=ready.put
            )
            client.sendto(encode(0, 0), ready.get(timeout=2))
            result = future.result(timeout=2)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["counts"]["wrong_peer"], 1)
        self.assertNotIn("echoed", result["counts"])

    def test_responder_send_failure(self):
        class FailedSend(REAL_SOCKET):
            def sendto(self, payload, target):
                raise OSError("injected echo failure")

        with REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM) as client:
            with (
                patch("src.foreground_io.socket.socket", FailedSend),
                responder() as (peer, future),
            ):
                client.sendto(encode(0, 0), peer)
                result = future.result(timeout=2)
        self.assertEqual(result["status"], "io_error")
        self.assertEqual(result["counts"]["socket_error"], 1)

    def test_cli_output_is_exclusive_and_complete(self):
        with tempfile.TemporaryDirectory() as directory, responder() as (peer, _):
            path = Path(directory) / "result.json"
            command = [
                sys.executable,
                "scripts/foreground.py",
                "client",
                "--port",
                "0",
                "--peer-port",
                str(peer[1]),
                "--warmup-ms",
                "0",
                "--measurement-ms",
                "100",
                "--drain-ms",
                "1001",
                "--output",
                str(path),
            ]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = path.read_bytes()
            self.assertEqual(len(json.loads(saved)["records"]), 50)
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=2)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(path.read_bytes(), saved)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_atomic_save_does_not_replace_file_or_leave_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            save_result(path, {"status": "test_fixture"})
            with self.assertRaises(FileExistsError):
                save_result(path, {"status": "replacement"})
            self.assertEqual(json.loads(path.read_text()), {"status": "test_fixture"})
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_cli_signal_saves_partial_evidence(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            REAL_SOCKET(socket.AF_INET, socket.SOCK_DGRAM) as peer,
        ):
            peer.bind(("127.0.0.1", 0))
            peer.settimeout(2)
            path = Path(directory) / "interrupted.json"
            child = subprocess.Popen(
                [
                    sys.executable,
                    "scripts/foreground.py",
                    "client",
                    "--port",
                    "0",
                    "--peer-port",
                    str(peer.getsockname()[1]),
                    "--output",
                    str(path),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                peer.recvfrom(513)
                child.send_signal(signal.SIGINT)
                _, stderr = child.communicate(timeout=3)
                self.assertEqual(child.returncode, 130, stderr)
                result = json.loads(path.read_text())
                self.assertEqual(result["status"], "cancelled")
                self.assertEqual(len(result["records"]), 35000)
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=2)

    def test_cli_rejects_unsafe_address_and_zero_responder_port(self):
        for args in (("--bind", "0.0.0.0"), ("--port", "0")):
            result = subprocess.run(
                [sys.executable, "scripts/foreground.py", "responder", *args],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=2,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Foreground endpoint failed:", result.stderr)
