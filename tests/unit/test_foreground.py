import random
import struct
import unittest

from src.foreground import MAX_EVENTS, Collector, Workload
from src.foreground_io import ReplyBudget, endpoint
from src.foreground_wire import MESSAGE_BYTES, PayloadMismatch, decode, encode
from src.measurement_contract import MAX_TIMESTAMP_NS, TIMEOUT_NS, RequestRecord


class WireTests(unittest.TestCase):
    def test_network_order_and_round_trip(self):
        expected = b"NQL1" + (1).to_bytes(4, "big") + (17).to_bytes(8, "big")
        expected += (101).to_bytes(8, "big")
        self.assertEqual(encode(17, 101)[:24], expected)
        rng = random.Random(7)
        for _ in range(100):
            pair = (rng.randrange(2**64), rng.randrange(MAX_TIMESTAMP_NS + 1))
            self.assertEqual(len(encode(*pair)), MESSAGE_BYTES)
            self.assertEqual(decode(encode(*pair)), pair)

    def test_rejects_bad_frames(self):
        good = encode(0, 0)
        for frame in (
            b"",
            good[:-1],
            good + b"x",
            b"BAD!" + good[4:],
            good[:4] + struct.pack("!I", 2) + good[8:],
            good[:16] + struct.pack("!Q", 2**63) + good[24:],
        ):
            with self.subTest(frame=frame[:24]), self.assertRaises(ValueError):
                decode(frame)
        with self.assertRaises(PayloadMismatch):
            decode(good[:-1] + bytes([good[-1] ^ 1]))
        for pair in ((True, 0), (-1, 0), (2**64, 0), (0, -1), (0, float("nan"))):
            with self.assertRaises(ValueError):
                encode(*pair)


class WorkloadTests(unittest.TestCase):
    def test_responder_budget_caps_burst_and_refill(self):
        budget = ReplyBudget(0)
        self.assertEqual(sum(budget.allow(0) for _ in range(100)), 32)
        self.assertFalse(budget.allow(999_999))
        self.assertTrue(budget.allow(1_000_000))
        self.assertFalse(budget.allow(1_000_000))
        self.assertEqual(sum(budget.allow(1_000_000_000) for _ in range(100)), 32)
        with self.assertRaises(ValueError):
            budget.allow(0)
        budget = ReplyBudget(0)
        self.assertTrue(all(budget.allow(i * 2_000_000) for i in range(1000)))

    def test_primary_counts_and_bounds(self):
        plan = Workload()
        self.assertEqual(plan.warmup_count, 5000)
        self.assertEqual(plan.total_count, 35000)
        self.assertEqual(plan.total_count - plan.warmup_count, 30000)
        for kwargs in (
            {"requests_per_second": True},
            {"measurement_ms": 0},
            {"warmup_ms": -1},
            {"requests_per_second": 501},
            {"drain_ms": 1000},
            {"max_in_flight": 1025},
            {"measurement_ms": 3},
            {"warmup_ms": 1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Workload(**kwargs)

    def test_endpoint_authority_is_explicit(self):
        for address, flag in ((2130706433, False), ("127.0.0.1", "yes")):
            with self.assertRaises(ValueError):
                endpoint(address, 42000, flag)
        self.assertEqual(endpoint("127.0.0.1", 0), ("127.0.0.1", 0))
        self.assertEqual(endpoint("192.168.1.10", 42000, True), ("192.168.1.10", 42000))
        for address, port, flag in (
            ("0.0.0.0", 42000, True),
            ("8.8.8.8", 42000, True),
            ("10.0.0.1", 42000, False),
            ("localhost", 42000, False),
            ("::1", 42000, False),
            ("127.0.0.1", 80, False),
            ("127.0.0.1", -1, False),
            ("127.0.0.1", True, False),
        ):
            with self.subTest(address=address, port=port), self.assertRaises(ValueError):
                endpoint(address, port, flag)


class CollectorTests(unittest.TestCase):
    def collector(self, **kwargs):
        return Collector(Workload(warmup_ms=0, measurement_ms=10, **kwargs), 0)

    def test_stall_records_missed_slots_without_catchup(self):
        c = self.collector()
        sent = []
        c.advance(7_000_001, lambda payload: sent.append(payload) or 7_000_001)
        self.assertEqual(sent, [])
        self.assertEqual(len(c.records), 4)
        self.assertEqual(c.event_counts["generator_late"], 4)
        c.advance(8_000_000, lambda payload: sent.append(payload) or 8_000_010)
        self.assertEqual(len(sent), 1)
        self.assertEqual(c.records[-1].scheduled_ns, 8_000_000)
        self.assertEqual(c.records[-1].sent_ns, 8_000_010)

    def test_reply_order_and_deadline_boundaries(self):
        c = self.collector()
        c.advance(0, lambda _: 10)
        c.advance(2_000_000, lambda _: 2_000_010)
        c.receive(encode(1, 2_000_000), 10 + TIMEOUT_NS)
        c.receive(encode(0, 0), 10 + TIMEOUT_NS + 1)
        self.assertEqual([r.outcome for r in c.records], ["late", "on_time"])
        c.receive(encode(1, 2_000_000), 2 * TIMEOUT_NS)
        self.assertEqual(c.records[1].received_ns, 10 + TIMEOUT_NS)
        self.assertEqual(c.event_counts["duplicate_reply"], 1)
        for r in c.finish("completed", c.end_ns)["records"]:
            RequestRecord.from_mapping(r)

    def test_expiration_frees_capacity_without_losing_history(self):
        c = Collector(Workload(warmup_ms=0, measurement_ms=1004, max_in_flight=1), 0)
        c.advance(0, lambda _: 0)
        c.advance(2_000_000, lambda _: self.fail("in-flight cap ignored"))
        self.assertEqual(c.event_counts["in_flight_limit"], 1)
        c.advance(TIMEOUT_NS, lambda _: self.fail("deadline must be inclusive"))
        c.advance(TIMEOUT_NS + 2_000_000, lambda _: TIMEOUT_NS + 2_000_000)
        self.assertEqual(c.active, {501})
        c.receive(encode(0, 0), TIMEOUT_NS + 3_000_000)
        self.assertEqual(c.records[0].outcome, "late")
        self.assertEqual(c.active, {501})

    def test_send_backpressure_and_io_error(self):
        def blocked(_):
            raise BlockingIOError()

        def broken(_):
            raise OSError("test failure")

        c = self.collector()
        c.advance(0, blocked)
        with self.assertRaises(OSError):
            c.advance(2_000_000, broken)
        self.assertEqual(c.event_counts["send_would_block"], 1)
        self.assertEqual(c.event_counts["send_error"], 1)
        result = c.finish("io_error", 3_000_000)
        self.assertEqual(len(result["records"]), 5)
        self.assertEqual(result["counts"]["measurement"]["not_sent"], 5)
        self.assertEqual(result["event_counts"]["not_attempted"], 3)

    def test_bad_replies_do_not_replace_valid_evidence(self):
        c = self.collector()
        c.advance(0, lambda _: 10)
        c.receive(b"short", 20)
        good = encode(0, 0)
        c.receive(good[:-1] + bytes([good[-1] ^ 1]), 20)
        c.receive(encode(5, 0), 20)
        c.receive(encode(0, 1), 20)
        c.receive(good, 9)
        for kind in (
            "malformed_reply",
            "payload_mismatch",
            "unknown_request",
            "request_mismatch",
            "clock_order_error",
        ):
            self.assertEqual(c.event_counts[kind], 1)
        self.assertIsNone(c.records[0].received_ns)
        c.receive(good, 30)
        self.assertEqual(c.records[0].rtt_ns, 20)
        self.assertEqual(c.records[0].completion_ns, 30)

    def test_bounded_events_keep_aggregate_counts(self):
        c = self.collector()
        for _ in range(MAX_EVENTS + 3):
            c.receive(b"bad", 0)
        result = c.finish("cancelled", 0)
        self.assertEqual(len(result["events"]), MAX_EVENTS)
        self.assertEqual(result["events_dropped"], 8)
        self.assertEqual(result["event_counts"]["malformed_reply"], MAX_EVENTS + 3)
        self.assertEqual(len(result["records"]), 5)

    def test_warmup_is_separate_even_if_reply_arrives_later(self):
        c = Collector(Workload(warmup_ms=2, measurement_ms=2), 100)
        c.advance(100, lambda _: 100)
        c.advance(2_000_100, lambda _: 2_000_100)
        c.receive(encode(0, 100), 3_000_100)
        result = c.finish("cancelled", 3_000_101)
        self.assertEqual(result["counts"]["warmup"]["on_time"], 1)
        self.assertEqual(result["counts"]["measurement"]["timeout"], 1)
        self.assertEqual(result["incomplete_deadlines"], 1)
        self.assertEqual(c.next_due_ns, c.end_ns)
        with self.assertRaises(ValueError):
            c.finish("made_up", 0)
        with self.assertRaises(ValueError):
            Collector(Workload(), MAX_TIMESTAMP_NS)
