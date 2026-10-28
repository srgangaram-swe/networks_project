import json
import unittest
from pathlib import Path

from src.experiment_config import ExperimentConfig
from src.measurement_contract import (
    DRAIN_SECONDS,
    MAX_IN_FLIGHT,
    MAX_TIMESTAMP_NS,
    TIMEOUT_NS,
    WARMUP_SECONDS,
    RequestRecord,
)


class RequestRecordTests(unittest.TestCase):
    def setUp(self):
        self.raw = {
            "schema_version": 1,
            "request_id": 7,
            "scheduled_ns": 1_000_000_000,
            "sent_ns": 1_000_100_000,
            "received_ns": 1_023_100_000,
        }

    def test_hand_calculated_latency_example(self):
        record = RequestRecord.from_mapping(json.loads(json.dumps(self.raw)))
        self.assertEqual(record.outcome, "on_time")
        self.assertEqual(record.rtt_ns, 23_000_000)
        self.assertEqual(record.completion_ns, 23_100_000)
        self.assertEqual(record.request_id, 7)

    def test_primary_plan_arithmetic_matches_decision(self):
        path = Path(__file__).resolve().parents[2] / "configs/primary.json"
        config = ExperimentConfig.from_mapping(json.loads(path.read_text()))
        self.assertEqual(config.total_runs, 280)
        self.assertEqual(config.foreground_requests_per_second * config.measurement_seconds, 30000)
        self.assertEqual(
            config.total_runs * (WARMUP_SECONDS + config.measurement_seconds + DRAIN_SECONDS),
            20160,
        )
        self.assertEqual(config.link_rate_mbps * 0.9 / 8, 11.25)
        self.assertEqual(MAX_IN_FLIGHT, 1024)

    def test_deadline_is_inclusive_and_late_reply_is_retained(self):
        for delta, outcome in ((TIMEOUT_NS, "on_time"), (TIMEOUT_NS + 1, "late")):
            record = RequestRecord.from_mapping(
                {**self.raw, "received_ns": self.raw["sent_ns"] + delta}
            )
            self.assertEqual(record.outcome, outcome)
            self.assertEqual(record.rtt_ns, delta)

    def test_missing_send_and_missing_reply_are_distinct(self):
        for sent, outcome in ((None, "not_sent"), (self.raw["sent_ns"], "timeout")):
            record = RequestRecord.from_mapping({**self.raw, "sent_ns": sent, "received_ns": None})
            self.assertEqual(record.outcome, outcome)
            self.assertIsNone(record.rtt_ns)
            self.assertIsNone(record.completion_ns)

    def test_exact_schema_and_version(self):
        for raw in ([], {}, {**self.raw, "extra": 0}, {**self.raw, "schema_version": 2}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                RequestRecord.from_mapping(raw)

    def test_types_bounds_and_clock_order(self):
        invalid = {
            "schema_version": (True, 1.0, None),
            "request_id": (True, -1, 2**64, "7"),
            "scheduled_ns": (True, -1, 1.0, MAX_TIMESTAMP_NS + 1),
            "sent_ns": (False, 0, MAX_TIMESTAMP_NS, float("nan")),
            "received_ns": (False, 0, MAX_TIMESTAMP_NS + 1, float("inf")),
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    RequestRecord.from_mapping({**self.raw, field: value})
        with self.assertRaisesRegex(ValueError, "requires a sent request"):
            RequestRecord.from_mapping({**self.raw, "sent_ns": None})

    def test_common_clock_offset_preserves_durations(self):
        before = dict(self.raw)
        reference = RequestRecord.from_mapping(self.raw)
        for offset in (0, 1, 10**12):
            shifted = {
                field: value + offset if field.endswith("_ns") else value
                for field, value in self.raw.items()
            }
            record = RequestRecord.from_mapping(shifted)
            self.assertEqual(record.rtt_ns, reference.rtt_ns)
            self.assertEqual(record.completion_ns, reference.completion_ns)
            self.assertEqual(record.outcome, reference.outcome)
        self.assertEqual(self.raw, before)

    def test_zero_duration_and_largest_safe_timestamp(self):
        for timestamp in (0, MAX_TIMESTAMP_NS - TIMEOUT_NS):
            record = RequestRecord.from_mapping(
                {
                    **self.raw,
                    "scheduled_ns": timestamp,
                    "sent_ns": timestamp,
                    "received_ns": timestamp,
                    "request_id": 2**64 - 1,
                }
            )
            self.assertEqual(record.rtt_ns, 0)
            self.assertEqual(record.outcome, "on_time")
