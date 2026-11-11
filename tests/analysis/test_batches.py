import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from analysis.policy_comparison import analyze
from src.artifacts import atomic_json, digest, read_json
from src.export_batches import export_inputs
from tests.analysis.support import fixture, write_export


class BatchAnalysisTests(unittest.TestCase):
    def test_full_matrix_keeps_pairing_across_47_indexed_chunks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = fixture(
                root / "fixture",
                blocks=10,
                policies=("fifo", "fq_codel", "cake_best_effort", "cake_bounded"),
                loads=(0.5, 0.9, 1.1),
                flows=(1, 8),
            )
            runs = pd.read_csv(source / "summary.csv", dtype={"run_id": str})
            requests = pd.read_csv(source / "requests.csv", dtype={"run_id": str})
            ledger = read_json(source / "attempts.json")
            export = root / "indexed"
            export.mkdir()
            atomic_json(export / "attempts.json", ledger)
            atomic_json(export / "versions.json", {"purpose": "temporary test fixture"})
            index = {
                "schema_version": 1,
                "kind": "diagnostic_export_batches",
                "state": "completed",
                "eligible_for_primary": False,
                "attempts_sha256": digest(export / "attempts.json"),
                "versions_sha256": digest(export / "versions.json"),
                "batches": [],
            }
            for start in range(0, len(runs), 6):
                chunk = runs.iloc[start : start + 6]
                manifests = set(chunk.manifest_sha256)
                design = {
                    **ledger,
                    "campaign_ledger_sha256": index["attempts_sha256"],
                    "attempts": [
                        a for a in ledger["attempts"] if a["manifest_sha256"] in manifests
                    ],
                }
                name = f"batch-{len(index['batches']) + 1:03d}"
                write_export(
                    export / name, chunk, requests[requests.run_id.isin(chunk.run_id)], design
                )
                index["batches"].append(
                    {
                        "directory": name,
                        "provenance_sha256": digest(export / name / "provenance.json"),
                    }
                )
            atomic_json(export / "index.json", index)
            report = analyze([export], root / "analysis", resamples=100)
            self.assertEqual(report["runs"], 280)
            self.assertEqual(report["unobserved_planned_cells"], 0)
            self.assertEqual(len(report["inputs"]), 47)
            self.assertEqual(len(report["comparisons"]), 24)
            self.assertEqual(len(report["ml"]["groups"]), 6)
            for comparison in report["comparisons"]:
                self.assertEqual(comparison["blocks"], 10)
                self.assertIsNotNone(comparison["added_p99_ms_ci_lower"])
                if comparison["policy"] == "fq_codel":
                    self.assertAlmostEqual(comparison["p99_reduction_pct"], 60)
                    self.assertAlmostEqual(comparison["goodput_retention_pct"], 95)
            for item in report["inputs"]:
                self.assertEqual(item["campaign_ledger_sha256"], index["attempts_sha256"])
            first = export / "batch-001"
            provenance = read_json(first / "provenance.json")
            atomic_json(first / "provenance.json", dict(provenance, changed=True))
            with self.assertRaisesRegex(ValueError, "batch provenance hash"):
                analyze([export], root / "corrupt", resamples=100, plots=False)
            atomic_json(first / "provenance.json", provenance)
            design = read_json(first / "attempts.json")
            design["campaign_ledger_sha256"] = "changed"
            atomic_json(first / "attempts.json", design)
            provenance["attempts_sha256"] = digest(first / "attempts.json")
            atomic_json(first / "provenance.json", provenance)
            index["batches"][0]["provenance_sha256"] = digest(first / "provenance.json")
            atomic_json(export / "index.json", index)
            with self.assertRaisesRegex(ValueError, "batch design"):
                analyze([export], root / "wrong-ledger", resamples=100, plots=False)

    def test_combined_run_row_bound_precedes_pairing_and_output_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "export"
            path.mkdir()
            inputs = export_inputs([path] * 21)
            with (
                patch("analysis.policy_comparison.export_inputs", return_value=inputs),
                patch(
                    "analysis.policy_comparison.load_data",
                    return_value=(pd.DataFrame({"run_id": range(20)}), None, {}),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "400 run rows"):
                    analyze([path], root / "output")
            self.assertFalse((root / "output").exists())
