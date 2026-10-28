import csv
import tempfile
import unittest
from pathlib import Path

from src.artifacts import atomic_json, digest, read_json
from src.diagnostics import _median_ms, export_diagnostics, nearest_rank, summarize
from tests.fixtures import valid_bundle


class DiagnosticTests(unittest.TestCase):
    def test_nearest_rank_and_even_median_are_hand_calculated(self):
        self.assertEqual(nearest_rank([1_000_000, 2_000_000, 9_000_000], 500), 2)
        self.assertEqual(nearest_rank([1_000_000, 2_000_000, 9_000_000], 990), 9)
        self.assertEqual(_median_ms([1_000_000, 4_000_000]), 2.5)
        self.assertIsNone(nearest_rank([], 990))
        self.assertIsNone(_median_ms([]))
        with self.assertRaises(ValueError):
            nearest_rank([1], 0)

    def test_per_run_summary_and_checked_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # Exercise the observed-data path with invented input only in this
            # temporary test. Public examples always retain the fixture label.
            bundle = valid_bundle(root / "synthetic-input", measurement_kind="loopback_diagnostic")
            summary, rows = summarize(bundle.directory)
            self.assertEqual(summary["p99_ms"], 1)
            self.assertEqual(summary["jitter_ms"], 0)
            self.assertEqual(summary["jitter_pairs"], 499)
            self.assertEqual(summary["send_lag_p99_ms"], 0.001)
            self.assertEqual(len(rows), 500)
            self.assertEqual(rows[0]["elapsed_seconds"], 0)
            destination = root / "synthetic-export"
            result = export_diagnostics([bundle.directory], destination)
            self.assertEqual(result["request_count"], 500)
            for name in ("summary.csv", "requests.csv"):
                payload = (destination / name).read_bytes()
                self.assertNotIn(b"\r", payload)
                self.assertTrue(payload.endswith(b"\n"))
            with (destination / "summary.csv").open() as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 1)
            with self.assertRaises(FileExistsError):
                export_diagnostics([bundle.directory], destination)
            for paths in ([], [bundle.directory, bundle.directory]):
                with self.assertRaises(ValueError):
                    export_diagnostics(paths, root / "invalid")

    def test_fixture_label_blocks_publication_as_observed_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "run"
            bundle = valid_bundle(root)
            environment = read_json(root / "environment.json")
            environment["measurement_kind"] = "synthetic_fixture"
            atomic_json(root / "environment.json", environment)
            bundle.manifest["artifacts"]["environment.json"] = digest(root / "environment.json")
            bundle.save()
            with self.assertRaisesRegex(ValueError, "synthetic fixtures"):
                summarize(root)


if __name__ == "__main__":
    unittest.main()
