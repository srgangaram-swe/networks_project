import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import mock_open, patch

from src.cpu import cpu_usage, parse_cpu, snapshot_cpu
from src.experiment_config import ExperimentConfig
from src.schedule import make_schedule


class ScheduleTests(unittest.TestCase):
    def test_paired_matrix_is_complete_deterministic_and_not_grouped_by_policy(self):
        root = Path(__file__).resolve().parents[2]
        config = ExperimentConfig.from_mapping(
            json.loads((root / "configs/primary.json").read_text())
        )
        first = make_schedule(config)
        self.assertEqual(first, make_schedule(config))
        cells = first["cells"]
        self.assertEqual(len(cells), 280)
        self.assertEqual(sum(cell["flows"] == 0 for cell in cells), 40)
        self.assertEqual(len({cell["cell_id"] for cell in cells}), 280)
        for cell in cells:
            self.assertEqual(sum(other["cell_id"] == cell["baseline_id"] for other in cells), 1)
        self.assertNotEqual(first, make_schedule(replace(config, random_seed=562)))
        with self.assertRaises(ValueError):
            make_schedule(replace(config, unloaded_repetitions_per_policy=9))
        with self.assertRaises(ValueError):
            make_schedule(replace(config, background_load_fractions=(0.501, 0.502)))


class CpuTests(unittest.TestCase):
    def test_guest_ticks_are_not_counted_twice(self):
        before = parse_cpu("cpu 10 0 5 80 5 0 0 0 3 0")
        after = parse_cpu("cpu 20 0 10 160 10 0 0 0 6 0")
        self.assertEqual(
            cpu_usage(before, after),
            {"scope": "shared_host", "busy_percent": 15, "iowait_percent": 5},
        )
        self.assertIsNone(cpu_usage(None, None)["busy_percent"])

    def test_malformed_reset_and_zero_windows_fail(self):
        for value in ("cpu 1 2", "cpu -1 0 0 0 0 0 0 0", "cpu0 1 2 3 4 5 6 7 8"):
            with self.assertRaises(ValueError):
                parse_cpu(value)
        for before, after in (((1,) * 8, (0,) * 8), ((0,) * 8, (0,) * 8), ((1,), (2,))):
            with self.assertRaises(ValueError):
                cpu_usage(before, after)

    def test_platform_adapter_uses_only_aggregate_line(self):
        with (
            patch("src.cpu.platform.system", return_value="Linux"),
            patch.object(Path, "open", mock_open(read_data="cpu 1 2 3 4 5 6 7 8\n")),
        ):
            self.assertEqual(snapshot_cpu(), (1, 2, 3, 4, 5, 6, 7, 8))
        with patch("src.cpu.platform.system", return_value="Darwin"):
            self.assertIsNone(snapshot_cpu())


if __name__ == "__main__":
    unittest.main()
