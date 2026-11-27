import copy
import unittest
from concurrent.futures import Future
from dataclasses import replace
from threading import Event
from unittest.mock import Mock, patch

from src.basic_rpc_protocol import rpc_connector as io
from src.basic_rpc_protocol import rpc_workload as work
from src.basic_rpc_protocol.rpc_client import RpcClient, RpcTimeout
from src.basic_rpc_protocol.rpc_metrics import RpcCallRecord, RpcMetrics
from src.basic_rpc_protocol.rpc_packet_protocol import (
    HEADER,
    MAX_PAYLOAD_BYTES,
    Packet,
    PacketKind,
    decode_packet,
    encode_packet,
)
from src.basic_rpc_protocol.rpc_server import RpcServer
from src.rpc_validation import validate_rpc, validate_rpc_artifacts
from src.trial import TrialConfig, unloaded_summary


def result_for(client, sequence, payload=b"ok"):
    return encode_packet(
        Packet(PacketKind.RESULT, client.machine_id, client.activity_id, sequence, payload)
    )


class PacketTests(unittest.TestCase):
    def test_roundtrip_all_kinds_and_boundaries(self):
        for kind in PacketKind:
            for payload in (b"", b"a" * MAX_PAYLOAD_BYTES):
                if kind == PacketKind.ACK and payload:
                    continue
                packet = Packet(kind, 2**64 - 1, 2**32 - 1, 2**64 - 1, payload)
                self.assertEqual(decode_packet(encode_packet(packet)), packet)
        with self.assertRaises(TypeError):
            encode_packet({})
        base = Packet(PacketKind.CALL, 1, 2, 3)
        for name, value in (
            ("kind", 1),
            ("machine_id", True),
            ("activity_id", -1),
            ("sequence", 2**64),
            ("payload", "text"),
            ("payload", b"x" * 483),
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                encode_packet(replace(base, **{name: value}))
        with self.assertRaises(ValueError):
            encode_packet(Packet(PacketKind.ACK, 1, 1, 1, b"x"))

    def test_malformed_wire_and_bounded_fuzz(self):
        wire = encode_packet(Packet(PacketKind.CALL, 1, 2, 3, b"x"))
        corrupt = [None, "text", b"", b"x" * 513, wire[:-1], wire + b"x"]
        for offset in (0, 4, 5, 7, 29):
            changed = bytearray(wire)
            changed[offset] = 255
            corrupt.append(bytes(changed))
        corrupt.append(HEADER.pack(b"BRPC", 1, 3, 0, 1, 2, 3, 1) + b"x")
        for data in corrupt:
            with self.subTest(data=data), self.assertRaises(ValueError):
                decode_packet(data)
        for length in range(513):
            with self.assertRaises(ValueError):
                decode_packet(bytes(length))


class ClientTests(unittest.TestCase):
    def test_limits_time_order_and_sequence_exhaustion(self):
        for kwargs in ({"timeout_ns": True}, {"timeout_ns": 1}, {"max_retries": -1}):
            with self.assertRaises(ValueError):
                RpcClient(1, 1, **kwargs)
        client = RpcClient(1, 2, timeout_ns=1000000, max_retries=0)
        self.assertIsNone(client.next_deadline_ns)
        self.assertIsNone(client.retry_due(0))
        client.start_call(b"x", 1)
        with self.assertRaises(RuntimeError):
            client.start_call(b"x", 2)
        with self.assertRaises(ValueError):
            client.retry_due(0)
        with self.assertRaises(RpcTimeout):
            client.retry_due(1000001)
        self.assertFalse(client.has_pending_call)
        client.sequence = 2**64 - 1
        with self.assertRaises(OverflowError):
            client.start_call(b"x", 1000002)
        with self.assertRaises(RuntimeError):
            client.take_result()

    def test_result_ownership_duplicate_old_result_and_consumption(self):
        client = RpcClient(1, 2)
        client.start_call(b"ok", 0)
        self.assertIsNone(client.handle_packet(b"malformed", 1))
        self.assertIsNone(client.handle_packet(result_for(client, 5), 2))
        client.handle_packet(result_for(client, 1), 3)
        with self.assertRaises(RuntimeError):
            client.start_call(b"ok", 4)
        self.assertEqual(client.take_result(), b"ok")
        client.start_call(b"second", 5)
        peer = ("127.0.0.1", 5300)
        sock = Mock()
        sock.recvfrom.side_effect = [(result_for(client, 1), peer), BlockingIOError()]
        sock.sendto.side_effect = lambda packet, address: len(packet)
        with patch.object(io.time, "monotonic_ns", return_value=6):
            self.assertFalse(io._receive_result(sock, client, peer))
        self.assertTrue(client.has_pending_call)
        self.assertEqual(client.statistics()["duplicate_results"], 1)
        sock.recvfrom.side_effect = [
            (b"bad", ("127.0.0.2", 5300)),
            (result_for(client, 2, b"second"), peer),
        ]
        with patch.object(io.time, "monotonic_ns", return_value=7):
            self.assertTrue(io._receive_result(sock, client, peer))
        self.assertEqual(client.take_result(), b"second")
        self.assertEqual(client.statistics()["wrong_peer"], 1)


class ServerTests(unittest.TestCase):
    def test_connector_rejects_invalid_inputs_and_bounds_unresponsive_sockets(self):
        peer = ("127.0.0.1", 5300)
        with self.assertRaises(TypeError):
            io.run_client(None, b"x", ("127.0.0.1", 0), peer)
        with self.assertRaises(ValueError):
            io.run_client(RpcClient(1, 1), b"x", peer, peer)
        with self.assertRaises(TypeError):
            io.run_server(None, peer, "127.0.0.1")
        stop = Event()
        stop.set()
        with self.assertRaises(InterruptedError):
            io.run_client(RpcClient(1, 1), b"x", ("127.0.0.1", 0), peer, stop=stop)
        with self.assertRaises(TimeoutError):
            io.run_client(RpcClient(1, 1), b"x", ("127.0.0.1", 0), peer, total_timeout_ms=1)
        client = RpcClient(1, 1)
        with patch.object(
            client, "retry_due", side_effect=lambda now: setattr(client, "_pending", None)
        ):
            with self.assertRaisesRegex(RuntimeError, "no outstanding"):
                io.run_client(client, b"x", ("127.0.0.1", 0), peer)
        with patch.object(io, "MAX_SERVER_PACKETS", 0):
            self.assertEqual(
                io.run_server(RpcServer(bytes), ("127.0.0.1", 0), "127.0.0.1", duration_ms=1)[
                    "status"
                ],
                "packet_limit",
            )
        self.assertEqual(
            io.run_server(RpcServer(bytes), ("127.0.0.1", 0), "127.0.0.1", duration_ms=1)["status"],
            "completed",
        )
        poll = Mock()
        poll.__enter__ = Mock(return_value=poll)
        poll.__exit__ = Mock(return_value=False)
        poll.select.side_effect = OSError(5, "read failed")
        with patch.object(io.selectors, "DefaultSelector", return_value=poll):
            result = io.run_server(RpcServer(bytes), ("127.0.0.1", 0), "127.0.0.1")
        self.assertEqual(result["status"], "io_error")
        self.assertEqual(result["socket_error_errno"], 5)

    def test_validation_old_calls_ack_limits_and_handler_errors(self):
        with self.assertRaises(TypeError):
            RpcServer(None)
        with self.assertRaises(ValueError):
            RpcServer(bytes, max_activities=0)
        server = RpcServer(lambda data: data, max_activities=1)
        call = Packet(PacketKind.CALL, 1, 2, 2, b"value")
        self.assertIsNone(server.handle_packet(b"bad"))
        reply = server.handle_packet(encode_packet(call))
        self.assertEqual(server.handle_packet(encode_packet(call)), reply)
        self.assertIsNone(server.handle_packet(encode_packet(replace(call, sequence=1))))
        self.assertIsNone(server.handle_packet(encode_packet(replace(call, activity_id=3))))
        self.assertIsNone(server.handle_packet(reply))
        for sequence in (1, 2, 2):
            self.assertIsNone(
                server.handle_packet(encode_packet(Packet(PacketKind.ACK, 1, 2, sequence)))
            )
        self.assertIsNone(server.handle_packet(encode_packet(call)))
        self.assertIsNotNone(server.handle_packet(encode_packet(replace(call, sequence=3))))
        self.assertEqual(server.statistics()["calls_executed"], 2)
        server = RpcServer(lambda data: "invalid")
        with self.assertRaises(TypeError):
            server.handle_packet(encode_packet(call))
        self.assertEqual(server.activities, {})

    def test_datagram_io_counters_and_partial_send(self):
        server = RpcServer(bytes)
        sock, counts = Mock(), io.Counter()
        peer = "127.0.0.1"
        sock.recvfrom.side_effect = BlockingIOError()
        io._serve_packet(sock, server, peer, counts)
        sock.recvfrom.side_effect = None
        sock.recvfrom.return_value = (b"x", ("127.0.0.2", 1))
        io._serve_packet(sock, server, peer, counts)
        sock.recvfrom.return_value = (b"x", (peer, 1))
        io._serve_packet(sock, server, peer, counts)
        sock.recvfrom.return_value = (encode_packet(Packet(PacketKind.CALL, 1, 1, 1)), (peer, 1))
        sock.sendto.side_effect = BlockingIOError()
        io._serve_packet(sock, server, peer, counts)
        self.assertEqual(counts["send_would_block"], 1)
        sock.sendto.side_effect = None
        sock.sendto.return_value = 0
        with self.assertRaises(OSError):
            io._send(sock, b"x", (peer, 1))


class MetricsAndWorkloadTests(unittest.TestCase):
    def test_metrics_use_successes_for_latency_and_all_calls_for_failure_rate(self):
        metrics = RpcMetrics(3)
        records = [
            RpcCallRecord(1, 1, n + 1, 0, ns, outcome, retry)
            for n, (ns, outcome, retry) in enumerate(
                [(1000000, "completed", 0), (9000000, "completed", 1), (1000000000, "timeout", 3)]
            )
        ]
        for record in records:
            metrics.add(record)
        result = metrics.summarize(client_counts={"calls_started": 3}, server_counts={})
        self.assertEqual(result["p50_ms"], 1)
        self.assertEqual(result["p99_ms"], 9)
        self.assertEqual(result["timeout_rate"], 1 / 3)
        self.assertEqual(result["retransmissions"], 4)
        self.assertEqual(len(metrics.request_rows()), 3)
        with self.assertRaises(ValueError):
            metrics.add(records[0])
        metrics = RpcMetrics(2)
        self.assertIsNone(metrics.summarize()["p99_ms"])
        with self.assertRaises(TypeError):
            metrics.add({})
        metrics.add(records[0])
        with self.assertRaises(ValueError):
            metrics.add(records[0])
        for kwargs in (
            {"outcome": "unknown"},
            {"finished_ns": -1},
            {"started_ns": 2, "finished_ns": 1},
            {"retransmissions": 21},
        ):
            with self.assertRaises(ValueError):
                replace(records[0], **kwargs)
        for value in (0, True, 100001):
            with self.assertRaises(ValueError):
                RpcMetrics(value)
        for counters in ([], {"": 1}, {"a": True}, {1: 1}):
            with self.assertRaises(ValueError):
                metrics.summarize(client_counts=counters)

    def test_configuration_and_cancellation_boundaries(self):
        base = work.RpcWorkloadConfig()
        for kwargs in (
            {"bind": ("127.0.0.1", 5300)},
            {"peer": ("127.0.0.1", 0)},
            {"allow_isolated": 1},
            {"measurement_seconds": 101, "requests_per_second": 1000},
            {"total_timeout_ms": 500},
            {"payload": "bad"},
            {"payload": b"x" * 483},
            {"workers": 257},
            {"machine_id": True},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(base, **kwargs)
        with self.assertRaises(TypeError):
            work.run_rpc_workload({})
        stop = Event()
        stop.set()
        result = work.run_rpc_workload(replace(base, measurement_seconds=1), stop=stop)
        self.assertEqual(result["cancelled_before_admission"], 500)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["requests"], [])
        stop.clear()
        with patch.object(work.time, "monotonic_ns", return_value=10):
            self.assertTrue(work._wait_until(9, stop))

    def test_worker_error_outcomes_and_activity_rotation(self):
        config = work.RpcWorkloadConfig(machine_id=7)
        for error, outcome, rotate in (
            (RpcTimeout(), "timeout", False),
            (TimeoutError(), "timeout", True),
            (InterruptedError(), "cancelled", True),
            (OSError(), "io_error", True),
        ):
            worker = work._CallWorkers(config, Event(), 7)
            with patch.object(work, "run_client", side_effect=error):
                record, _, lag, rotated = worker.execute_call(0)
            self.assertEqual(record.outcome, outcome)
            self.assertEqual(rotated, rotate)
            self.assertGreaterEqual(lag, 0)
        worker = work._CallWorkers(config, Event(), 7)
        worker.activities = iter([2**32])
        with self.assertRaises(OverflowError):
            worker.new_client()
        worker = work._CallWorkers(config, Event(), 7)
        with patch.object(work, "run_client", return_value=b"wrong"):
            with self.assertRaises(ValueError):
                worker.execute_call(0)

    def test_evidence_recomputation_rejects_forged_counts_and_durations(self):
        config = work.RpcWorkloadConfig(requests_per_second=1, measurement_seconds=1)
        future = Future()
        future.set_result((RpcCallRecord(1, 1, 1, 10, 1000010, "completed"), {}, 0, False))
        raw = work._results(config, 1, 1, 0, [future], 0, "completed")
        self.assertEqual(validate_rpc(raw)["p99_ms"], 1)
        for change in (
            {"schema_version": 9},
            {"status": "cancelled"},
            {"scheduled_calls": 2},
            {"requests": []},
            {"summary": {}},
            {"requests": [{**raw["requests"][0], "duration_ms": 5}]},
        ):
            with self.subTest(change=change), self.assertRaises((ValueError, KeyError)):
                validate_rpc({**raw, **change})
        validate_rpc_artifacts({}, TrialConfig())
        with self.assertRaises(ValueError):
            validate_rpc_artifacts({"rpc.json": raw}, TrialConfig())
        plan = TrialConfig(flows=0, aggregate_bps=0, measurement_seconds=1, rpc_diagnostics=True)
        with self.assertRaises(ValueError):
            validate_rpc_artifacts({}, plan)
        raw = copy.deepcopy(raw)
        raw.update(requests_per_second=500, scheduled_calls=500, skipped_capacity=499)
        artifacts = {
            "rpc.json": raw,
            "rpc-server.json": {"status": "cancelled"},
            "rpc-bulk.json": unloaded_summary(plan),
        }
        validate_rpc_artifacts(artifacts, plan)
        artifacts["rpc-server.json"]["status"] = "packet_limit"
        with self.assertRaises(ValueError):
            validate_rpc_artifacts(artifacts, plan)
        artifacts["rpc-server.json"]["status"] = "cancelled"
        raw["payload_bytes"] = 1
        with self.assertRaises(ValueError):
            validate_rpc_artifacts(artifacts, plan)
        raw["payload_bytes"] = 482
        artifacts["rpc-bulk.json"]["goodput_mbps"] = 5
        with self.assertRaises(ValueError):
            validate_rpc_artifacts(artifacts, plan)
