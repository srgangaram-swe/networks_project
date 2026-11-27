import contextlib
import io
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch

from src import shadow_runtime, tcp_observer_runtime
from src.artifacts import read_json
from tests.unit.test_transport import packet


class ObserverRuntimeTests(unittest.TestCase):
    def test_nonblocking_consumer_parses_one_event_and_retains_partial_streams(self):
        poll = MagicMock()
        poll.select.return_value = [True]
        manager = MagicMock()
        manager.__enter__.return_value = poll
        for data, message in (
            (b'{"kind":"send","observed_ns":1,"request_id":0}\n', None),
            (b"x" * 513 + b"\n", "budget"),
            (b"x" * 513, "budget"),
        ):
            with (
                patch.object(shadow_runtime.selectors, "DefaultSelector", return_value=manager),
                patch.object(shadow_runtime.os, "read", return_value=data),
                patch.object(shadow_runtime.time, "monotonic", side_effect=[0, 0, 2]),
                patch.object(shadow_runtime.time, "monotonic_ns", side_effect=[0, 2, 3]),
            ):
                if message:
                    with self.assertRaisesRegex(ValueError, message):
                        shadow_runtime.consume(0, Event(), 1, ready=lambda: None)
                else:
                    report = shadow_runtime.consume(0, Event(), 1)
                    self.assertEqual(report["events_received"], 1)
                    self.assertEqual(report["pending_requests"], 1)
        with (
            patch.object(shadow_runtime.selectors, "DefaultSelector", return_value=manager),
            patch.object(shadow_runtime.os, "read", return_value=b"{"),
            patch.object(shadow_runtime.time, "monotonic", side_effect=[0, 0, 2]),
            patch.object(shadow_runtime.time, "monotonic_ns", return_value=0),
        ):
            self.assertEqual(
                shadow_runtime.consume(0, Event(), 1, ready=lambda: None)["partial_event_bytes"], 1
            )

    def test_observer_reads_headers_and_reports_kernel_capture_quality(self):
        sock = MagicMock()
        sock.__enter__.return_value = sock
        sock.recv.side_effect = [BlockingIOError(), packet(payload=512)]
        sock.getsockopt.return_value = struct.pack("=II", 2, 1)
        poll = MagicMock()
        poll.select.return_value = [True]
        poll.__enter__.return_value = poll
        with (
            patch.object(tcp_observer_runtime, "require_linux"),
            patch.object(tcp_observer_runtime.socket, "AF_PACKET", 17, create=True),
            patch.object(tcp_observer_runtime.socket, "socket", return_value=sock),
            patch.object(tcp_observer_runtime.selectors, "DefaultSelector", return_value=poll),
            patch.object(tcp_observer_runtime.time, "monotonic", side_effect=[0, 0, 0, 2]),
            patch.object(
                tcp_observer_runtime.time,
                "monotonic_ns",
                side_effect=[0, 1_500_000_000, 1_500_000_001],
            ),
        ):
            report = tcp_observer_runtime.collect(
                "10.203.0.2", "10.203.0.6", 1, Event(), ready=lambda: None
            )
        self.assertEqual(report["observed_packets"], 1)
        self.assertEqual(report["capture_dropped"], 1)
        self.assertEqual(report["quality"], "capture_drops")
        sock.bind.assert_called_once_with(("eth0", 0))

    def test_monitor_cli_creates_private_fifo_and_durable_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            argv = [
                "shadow",
                "--events-fifo",
                str(root / "events"),
                "--output",
                str(root / "output.json"),
                "--duration",
                "1",
            ]

            def consume(descriptor, stop, duration, *, ready):
                ready()
                self.assertEqual(os.fstat(descriptor).st_mode & 0o777, 0o600)
                return {"mode": "shadow_only_no_policy_changes"}

            with (
                patch.object(sys, "argv", argv),
                patch.object(shadow_runtime, "consume", side_effect=consume),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(shadow_runtime.main(), 0)
            self.assertEqual(
                read_json(root / "output.json")["mode"], "shadow_only_no_policy_changes"
            )
            with patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(shadow_runtime.main(), 2)
            (root / "events").unlink()

    def test_passive_cli_publishes_only_a_new_owned_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "observer.json"
            argv = [
                "observer",
                "--output",
                str(path),
                "--client",
                "192.0.2.2",
                "--server",
                "198.51.100.2",
                "--duration",
                "1",
            ]

            def collect(*args, **kwargs):
                kwargs["ready"]()
                return {"capture_dropped": 0}

            with (
                patch.object(sys, "argv", argv),
                patch.object(tcp_observer_runtime, "collect", side_effect=collect),
                patch.object(tcp_observer_runtime.os, "geteuid", return_value=0),
                patch.object(tcp_observer_runtime.os, "chown") as chown,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(tcp_observer_runtime.main(), 0)
            chown.assert_called_once()
            self.assertEqual(read_json(path)["capture_dropped"], 0)
            with patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(tcp_observer_runtime.main(), 2)
