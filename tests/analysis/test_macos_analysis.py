import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analysis.policy_comparison import analyze
from analysis.utils.load_data import load_data
from analysis.utils.validate_data import numeric, quantile, required, validate_summaries
from src.artifacts import read_json
from tests.analysis.support import fixture, refresh


class MacAnalysisTests(unittest.TestCase):
    def test_macos_export_reaches_models_and_plots_with_explicit_topology(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = fixture(root / "export", blocks=4)
            rows = pd.read_csv(data / "summary.csv", dtype={"run_id": str})
            rows["measurement_kind"] = "macos_testbed"
            rows["platform"] = "Darwin"
            rows["cpu_scope"] = "unavailable"
            rows["cpu_busy_percent"] = None
            rows["cpu_iowait_percent"] = None
            rows.to_csv(data / "summary.csv", index=False)
            refresh(data)
            analyze([data], root / "analysis", resamples=100)
            report = read_json(root / "analysis/report.json")
            self.assertEqual(report["measurement_kind"], "macos_testbed")
            self.assertFalse(report["eligible_for_primary"])
            self.assertTrue((root / "analysis/insights.txt").is_file())

    def test_missing_summary_fields_values_and_invalid_transport_are_rejected(self):
        with self.assertRaises(ValueError):
            required(pd.DataFrame({"a": [1]}), ("missing",))
        with self.assertRaises(ValueError):
            numeric(pd.DataFrame({"a": [None]}), ("a",))
        self.assertIsNone(quantile([], 0.99))
        with tempfile.TemporaryDirectory() as temp:
            data = fixture(Path(temp) / "export")
            original = pd.read_csv(data / "summary.csv", dtype=str, keep_default_na=False)
            for altered in (
                original.iloc[:0].copy(),
                original.assign(transport="sctp"),
                original.assign(flows="0"),
            ):
                with self.assertRaises(ValueError):
                    validate_summaries(altered)
            rows = pd.read_csv(data / "requests.csv", dtype={"run_id": str})
            rows.iloc[1:].to_csv(data / "requests.csv", index=False)
            refresh(data)
            with self.assertRaisesRegex(ValueError, "request count"):
                load_data(data)
