import copy
import json
import unittest
from pathlib import Path

from src.experiment_config import ExperimentConfig

ROOT = Path(__file__).resolve().parents[2]


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads((ROOT / "configs/primary.json").read_text())

    def test_primary_counts_match_protocol(self):
        config = ExperimentConfig.from_mapping(self.raw)
        self.assertEqual((config.loaded_runs, config.unloaded_runs), (240, 40))
        self.assertEqual(config.total_runs, 280)
        self.assertEqual(config.measurement_seconds_total, 16800)
        self.assertEqual(config.random_seed, 561)

    def test_rejects_missing_extra_and_non_object_input(self):
        for raw in (None, [], {}, {**self.raw, "unknown": 1}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                ExperimentConfig.from_mapping(raw)

    def test_integer_fields_reject_booleans_and_bounds(self):
        fields = {
            "schema_version": (0, 2),
            "foreground_message_bytes": (0, 65537),
            "foreground_requests_per_second": (0, 100001),
            "repetitions": (1, 101),
            "measurement_seconds": (0, 3601),
            "unloaded_repetitions_per_policy": (1, 101),
            "random_seed": (-1, 2**32),
        }
        for field, bounds in fields.items():
            for value in (*bounds, True, False, 1.5, "10", None):
                raw = {**self.raw, field: value}
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    ExperimentConfig.from_mapping(raw)

    def test_numeric_fields_reject_invalid_values(self):
        for field in ("link_rate_mbps", "base_rtt_ms"):
            for value in (float("nan"), float("inf"), -1, 10001, True, "10", None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    ExperimentConfig.from_mapping({**self.raw, field: value})
        self.assertEqual(
            ExperimentConfig.from_mapping({**self.raw, "base_rtt_ms": 0}).base_rtt_ms, 0
        )

    def test_lists_reject_empty_duplicates_and_bad_items(self):
        for field in ("policies", "background_load_fractions", "background_flow_counts"):
            for value in ([], None, "fifo", [1] * 21, [1, 1], [{}]):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    ExperimentConfig.from_mapping({**self.raw, field: value})
        for field, value in (
            ("policies", ["unsupported"]),
            ("background_load_fractions", [0]),
            ("background_load_fractions", [float("nan")]),
            ("background_flow_counts", [129]),
            ("background_flow_counts", [False]),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                ExperimentConfig.from_mapping({**self.raw, field: value})

    def test_run_count_limit(self):
        raw = copy.deepcopy(self.raw)
        raw["background_load_fractions"] = [i / 10 for i in range(1, 21)]
        raw["background_flow_counts"] = list(range(1, 21))
        raw["repetitions"] = 100
        with self.assertRaisesRegex(ValueError, "10000-run"):
            ExperimentConfig.from_mapping(raw)

    def test_input_is_not_mutated(self):
        before = copy.deepcopy(self.raw)
        ExperimentConfig.from_mapping(self.raw)
        self.assertEqual(self.raw, before)
