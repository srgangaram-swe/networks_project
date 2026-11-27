"""Functional and failure-path tests for the basic RPC packet protocol."""

import queue
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from src.basic_rpc_protocol.rpc_client import RpcClient, RpcTimeout
from src.basic_rpc_protocol.rpc_connector import run_client, run_server
from src.basic_rpc_protocol.rpc_packet_protocol import PacketKind, decode_packet
from src.basic_rpc_protocol.rpc_server import RpcServer

TIMEOUT_NS = 1_000_000
MACHINE_ID = 123
ACTIVITY_ID = 1


class BasicRpcProtocolTests(unittest.TestCase):
    """Test RPC state changes using deterministic, caller-supplied times."""

    def setUp(self) -> None:
        self.executions: list[bytes] = []
        self.client = RpcClient(
            MACHINE_ID,
            ACTIVITY_ID,
            timeout_ns=TIMEOUT_NS,
            max_retries=2,
        )
        self.server = RpcServer(self._handle_call)

    def _handle_call(self, payload: bytes) -> bytes:
        """Record executions so duplicate suppression can be verified."""
        self.executions.append(payload)
        return payload.upper()

    def test_normal_request_response(self) -> None:
        """A successful call executes once and returns the matching result."""
        request = self.client.start_call(b"hello rpc", now_ns=0)
        self.assertEqual(decode_packet(request).kind, PacketKind.CALL)

        reply = self.server.handle_packet(request)
        self.assertIsNotNone(reply)
        self.assertEqual(decode_packet(reply).kind, PacketKind.RESULT)

        ack = self.client.handle_packet(reply, now_ns=1000)
        self.assertIsNotNone(ack)
        self.assertEqual(decode_packet(ack).kind, PacketKind.ACK)
        self.assertEqual(self.client.take_result(), b"HELLO RPC")
        self.assertEqual(self.executions, [b"hello rpc"])
        self.assertEqual(self.client.statistics()["calls_completed"], 1)

    def test_lost_request_is_retransmitted(self) -> None:
        """Dropping the first CALL causes a retry with the same identifiers."""
        request = self.client.start_call(b"request lost", now_ns=0)
        # Simulate packet loss by never delivering the original request.
        self.assertIsNone(self.client.retry_due(TIMEOUT_NS - 1))
        retry = self.client.retry_due(TIMEOUT_NS)
        self.assertEqual(retry, request)

        reply = self.server.handle_packet(retry)
        ack = self.client.handle_packet(reply, now_ns=TIMEOUT_NS + 1)
        self.server.handle_packet(ack)

        self.assertEqual(self.client.take_result(), b"REQUEST LOST")
        self.assertEqual(self.executions, [b"request lost"])
        self.assertEqual(self.client.statistics()["retransmissions"], 1)

    def test_lost_response_reuses_cached_reply(self) -> None:
        """A duplicate CALL must not execute the handler a second time."""
        request = self.client.start_call(b"response lost", now_ns=0)
        original_reply = self.server.handle_packet(request)
        # Simulate loss by discarding the RESULT without delivering it.
        retry = self.client.retry_due(TIMEOUT_NS)
        repeated_reply = self.server.handle_packet(retry)

        self.assertEqual(repeated_reply, original_reply)
        self.assertEqual(self.executions, [b"response lost"])
        self.assertEqual(self.server.statistics()["duplicate_calls"], 1)

        ack = self.client.handle_packet(repeated_reply, now_ns=TIMEOUT_NS + 1)
        self.server.handle_packet(ack)
        self.assertEqual(self.client.take_result(), b"RESPONSE LOST")

    def test_retry_exhaustion(self) -> None:
        """Calls fail after the configured number of retransmissions."""
        request = self.client.start_call(b"no server", now_ns=0)
        self.assertEqual(self.client.retry_due(TIMEOUT_NS), request)
        self.assertEqual(self.client.retry_due(2 * TIMEOUT_NS), request)

        with self.assertRaises(RpcTimeout):
            self.client.retry_due(3 * TIMEOUT_NS)

        self.assertFalse(self.client.has_pending_call)
        self.assertEqual(self.client.statistics()["retransmissions"], 2)
        self.assertEqual(self.client.statistics()["calls_timed_out"], 1)
        self.assertEqual(self.executions, [])

    def test_ack_releases_cached_reply(self) -> None:
        """An ACK clears the reply but retains sequence history."""
        request = self.client.start_call(b"first", now_ns=0)
        reply = self.server.handle_packet(request)
        ack = self.client.handle_packet(reply, now_ns=1000)
        self.assertIsNone(self.server.handle_packet(ack))
        self.assertEqual(self.server.statistics()["results_acked"], 1)
        self.assertEqual(self.client.take_result(), b"FIRST")

        # An acknowledged CALL must not run again, even after the reply is freed.
        self.assertIsNone(self.server.handle_packet(request))
        self.assertEqual(self.executions, [b"first"])

        next_request = self.client.start_call(b"second", now_ns=2000)
        next_reply = self.server.handle_packet(next_request)
        self.assertEqual(decode_packet(next_reply).sequence, 2)
        self.assertEqual(self.executions, [b"first", b"second"])

    def test_duplicate_result_is_acknowledged_again(self) -> None:
        """Duplicate results are harmless and trigger a repeated ACK."""
        request = self.client.start_call(b"again", now_ns=0)
        reply = self.server.handle_packet(request)
        ack = self.client.handle_packet(reply, now_ns=1000)

        self.assertEqual(self.client.handle_packet(reply, now_ns=2000), ack)
        self.assertEqual(self.client.statistics()["duplicate_results"], 1)
        self.assertEqual(self.client.take_result(), b"AGAIN")

    def test_unrelated_result_is_ignored(self) -> None:
        """A result for another activity cannot complete this client's call."""
        self.client.start_call(b"ours", now_ns=0)
        other = RpcClient(MACHINE_ID, ACTIVITY_ID + 1, timeout_ns=TIMEOUT_NS)
        other_request = other.start_call(b"other", now_ns=0)
        other_reply = self.server.handle_packet(other_request)

        self.assertIsNone(self.client.handle_packet(other_reply, now_ns=1000))
        self.assertTrue(self.client.has_pending_call)
        self.assertEqual(self.client.statistics()["unexpected_packets"], 1)

    def test_udp_loopback_round_trip(self) -> None:
        """Client and server exchange one call through real UDP sockets."""
        stop = Event()
        ready: queue.Queue[tuple[str, int]] = queue.Queue(maxsize=1)
        server = RpcServer(self._handle_call)
        client = RpcClient(MACHINE_ID, ACTIVITY_ID, timeout_ns=100_000_000)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                run_server,
                server,
                ("127.0.0.1", 0),
                "127.0.0.1",
                duration_ms=3000,
                stop=stop,
                ready=ready.put,
            )
            try:
                server_address = ready.get(timeout=2)
                result = run_client(
                    client,
                    b"udp loopback",
                    ("127.0.0.1", 0),
                    server_address,
                    total_timeout_ms=2000,
                )
                self.assertEqual(result, b"UDP LOOPBACK")
                self.assertEqual(self.executions, [b"udp loopback"])
            finally:
                stop.set()

            server_result = future.result(timeout=3)
            self.assertIn(server_result["status"], {"cancelled", "completed"})
            self.assertEqual(server.statistics()["calls_executed"], 1)


if __name__ == "__main__":
    unittest.main()
