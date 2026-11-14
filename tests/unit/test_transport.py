import contextlib
import io
import json
import os
import socket
import struct
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch

from src import foreground_tcp, shadow_runtime, tcp_observer_runtime
from src.event_stream import EventWriter
from src.foreground import Collector, Workload
from src.foreground_wire import encode
from src.online_regression import OnlineRidge
from src.shadow_forecast import SECOND, ShadowForecast, advice, percentile99
from src.tcp_observation import AckObserver, ahead, decode_header
from src.transport import parse_tcp_info, tcp_info, validate_transport


def packet(*, outbound=True, seq=100, ack=0, payload=0, flags=16, window=1000, vlan=False):
    addresses = (b"\xc0\x00\x02\x02", b"\xc6\x33\x64\x02")
    ports = (42001, 42000)
    if not outbound:
        addresses, ports = addresses[::-1], ports[::-1]
    ethernet = b"\0" * 12 + (b"\x81\x00\0\x01\x08\x00" if vlan else b"\x08\x00")
    ip = struct.pack("!BBHHHBBH4s4s", 69, 0, 40 + payload, 0, 0, 64, 6, 0, *addresses)
    tcp = struct.pack("!HHIIBBHHH", *ports, seq, ack, 80, flags, window, 0, 0)
    return ethernet + ip + tcp


class TransportTests(unittest.TestCase):
    def test_linux_socket_counter_offsets_and_platform_availability(self):
        data = bytearray(144)
        struct.pack_into("=I", data, 68, 1234)
        struct.pack_into("=I", data, 100, 7)
        struct.pack_into("=Q", data, 120, 2**35)
        self.assertEqual(parse_tcp_info(bytes(data))["rtt_us"], 1234)
        self.assertEqual(parse_tcp_info(bytes(data))["total_retransmissions"], 7)
        self.assertEqual(parse_tcp_info(bytes(data))["bytes_acked"], 2**35)
        self.assertNotIn("bytes_acked", parse_tcp_info(bytes(data[:104])))
        for invalid in (b"", b"x" * 103, None, data):
            with self.assertRaises(ValueError):
                parse_tcp_info(invalid)
        sock = MagicMock()
        with patch("src.transport.platform.system", return_value="Darwin"):
            self.assertEqual(tcp_info(sock)["status"], "unavailable_platform")
        with (
            patch("src.transport.platform.system", return_value="Linux"),
            patch.object(socket, "TCP_INFO", 11, create=True),
        ):
            sock.getsockopt.return_value = bytes(data)
            self.assertEqual(tcp_info(sock)["status"], "available")
            sock.getsockopt.side_effect = OSError(22, "not supported")
            self.assertEqual(tcp_info(sock)["status"], "unavailable_socket")
        self.assertEqual(validate_transport("tcp"), "tcp")
        with self.assertRaises(ValueError):
            validate_transport("sctp")

    def test_header_parser_rejects_truncation_fragments_and_wrong_protocols(self):
        self.assertEqual(decode_header(packet(vlan=True))["source_port"], 42001)
        self.assertEqual(decode_header(packet(payload=100))["payload_bytes"], 100)
        for length in (0, 13, 14, 30, 53):
            self.assertIsNone(decode_header(packet()[:length]))
        self.assertIsNone(decode_header(packet(vlan=True)[:16]))
        for offset, value in ((12, 0), (14, 0x44), (14, 0x65), (23, 17), (26, 0), (46, 0x40)):
            data = bytearray(packet())
            data[offset] = value
            if offset == 26:
                data[20] = 0x20
            self.assertIsNone(decode_header(data))
        data = bytearray(packet())
        data[16:18] = b"\0\x14"
        self.assertIsNone(decode_header(data))

    def test_duplicate_ack_candidates_require_outstanding_data_and_unchanged_window(self):
        observer = AckObserver("192.0.2.2", "198.51.100.2", 0)
        observer.observe(packet(seq=100, payload=512), 1)
        observer.observe(packet(outbound=False, ack=100), 2)
        observer.observe(packet(outbound=False, ack=100), 3)
        observer.observe(packet(outbound=False, ack=100, window=999), 4)
        observer.observe(packet(outbound=False, ack=100, payload=512, window=999), 5)
        observer.observe(packet(outbound=False, ack=612, window=999), 6)
        observer.observe(packet(outbound=False, ack=612, window=999), 7)
        counts = observer.report()["windows"][0]
        self.assertEqual(counts["foreground_duplicate_ack_candidates"], 1)
        observer.observe(packet(seq=100, payload=512), 8)
        self.assertEqual(
            observer.report()["windows"][0]["foreground_repeated_sequence_candidates"], 1
        )
        self.assertTrue(ahead(5, 2**32 - 5))
        self.assertFalse(ahead(2**32 - 5, 5))
        self.assertFalse(ahead(1, 1))
        observer.observe(b"", 9)
        observer.observe(packet(outbound=False, flags=2), 10)
        observer.observe(packet(), 11)
        with self.assertRaises(ValueError):
            observer.observe(packet(), 191 * SECOND)
        observer.packets = 2_000_000
        with self.assertRaises(ValueError):
            observer.observe(packet(), 12)
        other = AckObserver("203.0.113.1", "203.0.113.2", 0)
        other.observe(packet(), 1)
        self.assertEqual(other.report()["observed_flows"], 0)
        observer = AckObserver("192.0.2.2", "198.51.100.2", 0)
        observer.flows = {index: {} for index in range(64)}
        with self.assertRaises(ValueError):
            observer.observe(packet(), 1)

    def test_reverse_bulk_data_uses_client_acknowledgments(self):
        observer = AckObserver("192.0.2.2", "198.51.100.2", 0)
        data = bytearray(packet(outbound=False, seq=100, payload=1000))
        struct.pack_into("!HH", data, 34, 5201, 50000)
        ack = bytearray(packet(ack=100))
        struct.pack_into("!HH", ack, 34, 50000, 5201)
        observer.observe(bytes(data), 1)
        observer.observe(bytes(ack), 2)
        observer.observe(bytes(ack), 3)
        self.assertEqual(observer.report()["windows"][0]["bulk_duplicate_ack_candidates"], 1)

    def test_atomic_fifo_writes_drop_without_blocking_and_reject_regular_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events"
            path.touch(mode=0o600)
            with self.assertRaises(PermissionError):
                EventWriter(path)
            path.unlink()
            os.mkfifo(path, 0o600)
            with os.fdopen(os.open(path, os.O_RDWR | os.O_NONBLOCK), "rb") as reader:
                with EventWriter(path) as writer:
                    writer({"kind": "send", "observed_ns": 1})
                    message = os.read(reader.fileno(), 512)
                    self.assertEqual(message.count(b"\n"), 1)
                    self.assertEqual(json.loads(message)["kind"], "send")
                    self.assertEqual(writer.sent, 1)
                    for failure in (BlockingIOError(), BrokenPipeError()):
                        with patch("src.event_stream.os.write", side_effect=failure):
                            writer({"kind": "send"})
                    self.assertEqual(writer.dropped, 2)
                    with patch("src.event_stream.os.write", return_value=0):
                        with self.assertRaises(OSError):
                            writer({})
                    with self.assertRaises(ValueError):
                        writer({"data": "x" * 512})
            with EventWriter() as writer:
                writer({})
                self.assertEqual(writer.sent, 0)
            writer.close()

    def test_tcp_partial_send_and_fragmented_receive_preserve_framing(self):
        sock = MagicMock()
        sock.send.side_effect = [100, BlockingIOError(), 412]
        with patch("src.foreground_tcp.select.select", return_value=([], [sock], [])):
            self.assertGreater(foreground_tcp.send_frame(sock, b"x" * 512, Event()), 0)
        sock.send.return_value, sock.send.side_effect = 0, None
        with self.assertRaises(ConnectionResetError):
            foreground_tcp.send_frame(sock, b"x" * 512, Event())
        sock.send.side_effect = [100, 0]
        with patch("src.foreground_tcp.select.select", return_value=([], [sock], [])):
            with self.assertRaises(ConnectionResetError):
                foreground_tcp.send_frame(sock, b"x" * 512, Event())
        sock.send.side_effect = [100]
        stopped = Event()
        stopped.set()
        with self.assertRaises(InterruptedError):
            foreground_tcp.send_frame(sock, b"x" * 512, stopped)
        sock.send.side_effect = [100]
        with patch("src.foreground_tcp.time.monotonic", side_effect=[0, 1]):
            with self.assertRaises(TimeoutError):
                foreground_tcp.send_frame(sock, b"x" * 512, Event())
        collector = Collector(Workload(0, 2, 1001, 500), 0)
        collector.advance(0, lambda _: 0)
        data, buffer = encode(0, 0), bytearray()
        sock.recv.side_effect = [data[:100], BlockingIOError(), data[100:]]
        with patch("src.foreground_tcp.time.monotonic_ns", return_value=20_000_000):
            for _ in range(3):
                foreground_tcp._receive(sock, buffer, collector)
        self.assertEqual(len(buffer), 0)
        self.assertEqual(collector.records[0].received_ns, 20_000_000)
        sock.recv.side_effect = None
        sock.recv.return_value = b""
        with self.assertRaises(ConnectionResetError):
            foreground_tcp._receive(sock, buffer, collector)


class ShadowTests(unittest.TestCase):
    def test_recursive_ridge_matches_independent_one_dimensional_closed_form(self):
        model = OnlineRidge(1)
        model.update([2.0], 2.0)
        self.assertAlmostEqual(model.predict([1]), 4 / 5)
        model.update([1.0], 3.0)
        self.assertAlmostEqual(model.predict([1]), 7 / 6)
        for dimensions in (0, 17):
            with self.assertRaises(ValueError):
                OnlineRidge(dimensions)
        for features in ([], [float("nan")]):
            with self.assertRaises(ValueError):
                model.predict(features)
        with self.assertRaises(ValueError):
            model.update([1], float("inf"))
        self.assertEqual(percentile99([2, 1, 3]), 3)
        self.assertIsNone(percentile99([]))

    def run_model(self, changed_after=100):
        model = ShadowForecast(0)
        for second in range(30):
            model.advance(second * SECOND)
            stamp = second * SECOND + 10_000_000
            model.observe({"kind": "send", "request_id": second, "observed_ns": stamp}, stamp)
            latency = 20 if second < changed_after else 800
            reply = stamp + latency * 1_000_000
            model.observe({"kind": "reply", "request_id": second, "observed_ns": reply}, reply)
            model.observe({"kind": "tcp_window", "observed_ns": reply}, reply)
        return model

    def test_future_outcomes_do_not_change_prior_predictions_or_training_counts(self):
        normal, changed = self.run_model(), self.run_model(changed_after=20)
        for target in range(1, 21):
            self.assertEqual(
                normal.forecasts[target]["prediction"], changed.forecasts[target]["prediction"]
            )
            self.assertLess(
                normal.forecasts[target]["issued_ns"], normal.forecasts[target]["target_start_ns"]
            )
        self.assertNotEqual(normal.forecasts[29]["prediction"], changed.forecasts[29]["prediction"])
        self.assertIsNone(normal.forecasts[1]["prediction"]["p99_ms"])
        self.assertGreater(normal.forecasts[29]["training_windows"]["p99_ms"], 5)
        self.assertFalse(normal.report()["packet_loss_labels_available"])

    def test_timeout_labels_missing_events_and_limits_remain_explicit(self):
        model = ShadowForecast(0)
        model.advance(0)
        for kind, stamp in (
            ("send", SECOND + 1),
            ("deadline", 2 * SECOND + 2),
            ("reply", 2 * SECOND + 3),
        ):
            model.observe({"kind": kind, "request_id": 0, "observed_ns": stamp}, stamp)
        model.advance(5 * SECOND)
        self.assertEqual(model.forecasts[1]["actual"]["timeout_fraction"], 1)
        self.assertIsNone(model.forecasts[1]["actual"]["p99_ms"])
        model.observe({"kind": "send", "request_id": 1, "observed_ns": 5 * SECOND}, 5 * SECOND)
        model.advance(9 * SECOND)
        self.assertEqual(model.forecasts[6]["actual"], {})
        model.observe({"kind": "send", "request_id": 2, "observed_ns": 1}, 10 * SECOND)
        self.assertEqual(model.late_events, 1)
        for event in (
            {"observed_ns": -1},
            {"observed_ns": 20 * SECOND},
            {"observed_ns": 10 * SECOND, "kind": "unknown"},
        ):
            with self.assertRaises(ValueError):
                model.observe(event, 10 * SECOND)
        with self.assertRaises(ValueError):
            model.advance(191 * SECOND)
        self.assertEqual(
            advice({"p99_ms": 70, "timeout_fraction": 0}), "inspect_queue_and_offered_load"
        )
        self.assertEqual(advice({"p99_ms": 10, "timeout_fraction": 0}), "observe")

    def test_monitor_cli_guards_and_passive_collector_guard(self):
        for module, argv in (
            (
                shadow_runtime,
                [
                    "monitor",
                    "--duration",
                    "0",
                    "--events-fifo",
                    "/missing/a",
                    "--output",
                    "/missing/b",
                ],
            ),
            (
                tcp_observer_runtime,
                [
                    "observer",
                    "--duration",
                    "0",
                    "--client",
                    "127.0.0.1",
                    "--server",
                    "127.0.0.1",
                    "--output",
                    "/missing/b",
                ],
            ),
        ):
            with patch("sys.argv", argv), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(module.main(), 2)
        with patch("src.tcp_observer_runtime.require_linux"):
            with self.assertRaises(ValueError):
                tcp_observer_runtime.collect("127.0.0.1", "127.0.0.1", 0, Event())
        with self.assertRaises(ValueError):
            shadow_runtime.consume(0, Event(), 0)
