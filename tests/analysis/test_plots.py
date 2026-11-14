import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis.plot_artifacts import TABLE_FILES, expected_artifacts
from analysis.plots import render_plots
from analysis.plots.clusters import cluster_metrics_plot, cluster_profile_plot
from analysis.plots.diagnostics import request_outcome_plot, tail_quantile_plot
from analysis.plots.style import audit_layout, figure_grid
from analysis.run_clustering import cluster_runs
from analysis.utils.compare_policies import compare_policies
from analysis.utils.load_data import load_data
from analysis.utils.match_baselines import match_baselines
from tests.analysis.support import fixture


class PlotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        path = fixture(self.root / "input", blocks=2)
        self.runs, _, _ = load_data(path)

    def test_layout_rejects_inside_key_and_clipping_but_ignores_unrendered_ticks(self):
        fig, axes, _ = figure_grid(1, 1, "Layout regression")
        self.addCleanup(plt.close, fig)
        axis = axes[0]
        axis.plot([0, 1], [0, 1], label="Data")
        axis.legend(loc="center")
        with self.assertRaisesRegex(ValueError, "1 legend overlaps"):
            audit_layout(fig)
        axis.get_legend().remove()
        # Locators may retain ticks outside the current viewport; those are not drawn.
        axis.set_xticks([-100, 0, 1, 100])
        axis.set_xlim(0, 1)
        self.assertEqual(audit_layout(fig)["text_overflow_count"], 0)
        fig.text(2, 0.5, "Outside image")
        with self.assertRaisesRegex(ValueError, "Outside image"):
            audit_layout(fig)

    def test_request_bars_reconcile_all_slots_and_do_not_mutate_inputs(self):
        runs = self.runs.copy()
        runs.loc[:, "not_sent"] = 5
        runs.loc[:, "on_time"] = 490
        runs.loc[:, "timeout_count"] = 5
        before = runs.copy(deep=True)
        with patch("analysis.plots.diagnostics.save_figure") as save:
            request_outcome_plot(runs, self.root / "delivery.png")
        fig = save.call_args.args[0]
        self.addCleanup(plt.close, fig)
        for axis in fig.axes[:2]:
            bars = axis.containers
            self.assertEqual(len(bars), 3)
            for index in range(2):
                self.assertAlmostEqual(sum(group[index].get_width() for group in bars), 100)
                self.assertAlmostEqual(bars[1][index].get_width(), 1)
                self.assertAlmostEqual(bars[2][index].get_width(), 1)
        pd.testing.assert_frame_equal(runs, before)

    def test_quantile_heatmap_uses_run_means_and_retains_missing_values(self):
        before = self.runs.copy(deep=True)
        with patch("analysis.plots.diagnostics.save_figure") as save:
            tail_quantile_plot(self.runs, self.root / "quantiles.png")
        fig = save.call_args.args[0]
        self.addCleanup(plt.close, fig)
        loaded = self.runs[self.runs.flows > 0]
        expected = loaded.groupby("policy").p99_ms.mean().reindex(["fifo", "fq_codel"])
        actual = np.asarray(fig.axes[1].collections[0].get_array()).reshape(2, 4)
        np.testing.assert_allclose(actual[:, 2], expected)
        pd.testing.assert_frame_equal(self.runs, before)
        changed = self.runs.copy()
        changed.loc[changed.flows == 0, ["p50_ms", "p95_ms", "p99_ms", "p999_ms"]] = np.nan
        changed.loc[changed.policy == "fifo", "p999_ms"] = np.nan
        tail_quantile_plot(changed, self.root / "missing.png")
        changed.loc[:, ["p50_ms", "p95_ms", "p99_ms", "p999_ms"]] = np.nan
        tail_quantile_plot(changed, self.root / "all-missing.png")

    def test_unavailable_clusters_have_only_statistical_figures(self):
        assignments, model = cluster_runs(self.runs)
        self.assertTrue(assignments.empty)
        result = render_plots(
            self.runs,
            match_baselines(self.runs),
            compare_policies(self.runs, n_resamples=100),
            assignments,
            model,
            self.root / "plots",
        )
        self.assertEqual(
            set(result),
            {
                "policy_comparisons",
                "request_outcomes",
                "tail_quantiles",
                "ridge_lasso_predictions",
                "ridge_lasso_coefficients",
                "analysis_runtime",
            },
        )
        self.assertIsNone(cluster_metrics_plot(self.runs, assignments, self.root / "none.png"))
        self.assertIsNone(cluster_profile_plot(assignments, model, self.root / "none.png"))
        report = {"plot_bundle_version": 2, "plots_requested": True, "ml": model}
        self.assertEqual(len(expected_artifacts(report)), len(TABLE_FILES) + 6)
        report["plots_requested"] = False
        self.assertEqual(expected_artifacts(report), TABLE_FILES)
        self.assertEqual(len(expected_artifacts({})), 10)
        for invalid in (True, 0, 4, "2"):
            with self.assertRaises(ValueError):
                expected_artifacts({"plot_bundle_version": invalid})
