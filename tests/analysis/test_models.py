import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.cluster_diagnostics import canonical_labels, compare_partitions, partition_metrics
from analysis.plots.models import coefficient_plot, prediction_plot
from analysis.regression import FEATURES, regress_runs


def design_rows():
    rows = []
    for block in range(6):
        for index, policy in enumerate(("fifo", "fq_codel", "cake_best_effort", "cake_bounded")):
            rows.append(
                {
                    "run_id": f"{block * 4 + index:032x}",
                    "block": f"b{block}",
                    "policy": policy,
                    "requested_mbps": 110.0,
                    "flows": 1,
                    "added_p99_ms": 20 - index * 5 + (block - 2.5) * 0.1,
                }
            )
    return pd.DataFrame(rows)


class ModelTests(unittest.TestCase):
    def test_partition_scores_match_hand_computation_and_retain_noise(self):
        values = np.array([[0, 0], [0, 1], [10, 0], [10, 1]], dtype=float)
        labels = np.array([0, 0, 1, 1])
        result = partition_metrics(values, labels)
        self.assertAlmostEqual(result["davies_bouldin"], 0.1)
        self.assertAlmostEqual(result["calinski_harabasz"], 200)
        self.assertEqual(result["noise_runs"], 0)
        agglomerative, density, diagnostics = compare_partitions(values, labels)
        np.testing.assert_array_equal(agglomerative, labels)
        np.testing.assert_array_equal(density, [-1, -1, -1, -1])
        self.assertEqual(diagnostics["partitions"]["dbscan"]["noise_fraction"], 1)
        self.assertIsNone(diagnostics["partitions"]["dbscan"]["silhouette"])
        np.testing.assert_array_equal(
            canonical_labels(values, np.array([5, 5, 4, -1])), [0, 0, 1, -1]
        )

    def test_nested_blocks_preserve_all_runs_and_beat_training_mean_on_linear_fixture(self):
        rows = design_rows()
        predictions, report = regress_runs(rows)
        repeated, metadata = regress_runs(rows.sample(frac=1, random_state=5))
        pd.testing.assert_frame_equal(predictions, repeated)
        self.assertEqual(report, metadata)
        self.assertEqual(report["features"], FEATURES)
        self.assertEqual(len(predictions), 2 * len(rows))
        for name, details in report["models"].items():
            self.assertLess(details["mae_ms"], details["mean_baseline_mae_ms"])
            for fold in details["outer_folds"]:
                self.assertFalse(set(fold["train_blocks"]) & set(fold["test_blocks"]))
            self.assertEqual(predictions[predictions.model == name].run_id.nunique(), len(rows))
        changed = rows.copy()
        changed.loc[changed.block == "b0", "added_p99_ms"] += 1000
        altered, _ = regress_runs(changed)
        original = predictions[predictions.block == "b0"]
        held_out = altered[altered.block == "b0"]
        np.testing.assert_allclose(original.predicted_ms, held_out.predicted_ms)
        np.testing.assert_allclose(original.selected_alpha, held_out.selected_alpha)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            predictions.attrs["measurement_kind"] = "simulation"
            for function in (prediction_plot, coefficient_plot):
                audit = function(predictions, report, root / f"{function.__name__}.png")
                self.assertEqual(audit["legend_overlap_count"], 0)
                self.assertEqual(audit["text_overflow_count"], 0)

    def test_insufficient_and_missing_targets_do_not_generate_predictions(self):
        rows = design_rows()
        small, details = regress_runs(rows[rows.block.isin(["b0", "b1"])])
        self.assertTrue(small.empty)
        self.assertIn("fewer_than_six", details["status"])
        for missing in (np.nan, np.inf):
            changed = rows.copy()
            changed.loc[0, "added_p99_ms"] = missing
            unavailable, details = regress_runs(changed)
            self.assertTrue(unavailable.empty)
            self.assertEqual(details["status"], "unavailable_missing_target")
