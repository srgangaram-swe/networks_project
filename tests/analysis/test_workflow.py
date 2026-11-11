import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from analysis import policy_comparison
from analysis.plots import clustering_plot, comparison_plot
from analysis.run_clustering import FEATURES, cluster_runs
from analysis.utils.compare_policies import compare_policies
from analysis.utils.load_data import load_data
from analysis.utils.match_baselines import match_baselines
from src.artifacts import digest, read_json
from tests.analysis.support import ROOT, fixture


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = fixture(
            self.root / "input",
            blocks=2,
            policies=("fifo", "fq_codel", "cake_best_effort", "cake_bounded"),
        )
        self.runs, _, _ = load_data(self.input)

    def test_clustering_and_tsne_are_seeded_and_invariant_to_row_order(self):
        first, metadata = cluster_runs(self.runs)
        second, repeated = cluster_runs(self.runs.sample(frac=1, random_state=9))
        pd.testing.assert_frame_equal(first, second)
        self.assertEqual(metadata, repeated)
        self.assertEqual(len(first), 8)
        self.assertEqual(set(first.cluster), {0, 1})
        self.assertTrue(
            np.isfinite(first[["pc1", "pc2", "tsne1", "tsne2", "centroid_distance"]]).all().all()
        )
        self.assertNotIn("policy", metadata["features"])
        self.assertFalse(metadata["automatic_exclusions"])
        self.assertLess(metadata["groups"][0]["tsne"]["perplexity"], len(first))
        for bad, reason in ((self.runs.iloc[:2], "fewer_than_eight"),):
            self.assertIn(reason, cluster_runs(bad)[1]["groups"][0]["status"])
        for value, reason in ((np.nan, "missing_features"), (1, "insufficient_variation")):
            changed = self.runs.copy()
            changed[list(FEATURES)] = changed[list(FEATURES)].astype(float)
            changed.loc[:, list(FEATURES)] = value
            self.assertIn(reason, cluster_runs(changed)[1]["groups"][0]["status"])
        with self.assertRaises(ValueError):
            cluster_runs(self.runs, seed=None)

    def test_complete_workflow_retains_hashes_and_refuses_overwrite(self):
        output = self.root / "output"
        report = policy_comparison.analyze([self.input], output, resamples=100)
        self.assertEqual(report["state"], "completed")
        self.assertEqual(report["runs"], 16)
        self.assertFalse(report["eligible_for_primary"])
        self.assertTrue((output / "run_clusters_tsne.png").exists())
        self.assertIn("Primary eligibility: false", (output / "diagnostic_summary.txt").read_text())
        self.assertIn("Unavailable ratios", (output / "diagnostic_summary.txt").read_text())
        self.assertIn(r"cake\_bounded", (output / "writeup_table.tex").read_text())
        for name, checksum in report["artifacts"].items():
            self.assertEqual(digest(output / name), checksum)
        with self.assertRaises(FileExistsError):
            policy_comparison.analyze([self.input], output, resamples=100)
        with self.assertRaises(ValueError):
            policy_comparison.analyze(
                [self.input, self.input], self.root / "duplicate", resamples=100
            )
        with self.assertRaises(ValueError):
            policy_comparison.analyze([], self.root / "empty", resamples=100)

    def test_cli_success_and_failure_return_codes(self):
        args = [
            "policy_comparison",
            str(self.input),
            "--output",
            str(self.root / "cli"),
            "--resamples",
            "100",
            "--no-plots",
        ]
        with patch.object(sys, "argv", args), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(policy_comparison.main(), 0)
        with patch.object(sys, "argv", args), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(policy_comparison.main(), 2)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "analysis.policy_comparison",
                str(self.input),
                "--output",
                str(self.root / "subprocess"),
                "--resamples",
                "100",
                "--no-plots",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_partial_output_and_secondary_persistence_failure_preserve_cause(self):
        error = OSError("disk full")
        with patch("analysis.policy_comparison.comparison_plot", side_effect=error):
            with self.assertRaises(OSError) as caught:
                policy_comparison.analyze([self.input], self.root / "failed", resamples=100)
        self.assertIs(caught.exception, error)
        self.assertEqual(read_json(self.root / "failed/report.json")["state"], "failed")
        from src.artifacts import atomic_json

        def save(path, value):
            if value["state"] == "failed":
                raise OSError("report write failed")
            atomic_json(path, value)

        with (
            patch("analysis.policy_comparison.comparison_plot", side_effect=error),
            patch("analysis.policy_comparison.atomic_json", side_effect=save),
        ):
            with self.assertRaises(OSError) as caught:
                policy_comparison.analyze([self.input], self.root / "failed-again", resamples=100)
        self.assertIn("report write failed", caught.exception.__notes__[-1])

    def test_plots_for_three_blocks_and_empty_cluster_group(self):
        path = fixture(self.root / "three-blocks")
        runs, _, _ = load_data(path)
        comparison_plot(
            match_baselines(runs),
            compare_policies(runs, n_resamples=100),
            self.root / "intervals.png",
        )
        clustering_plot(pd.DataFrame(), self.root / "empty.png")
        self.assertFalse((self.root / "empty.png").exists())
        runs.loc[runs.flows > 0, "p99_censored"] = True
        comparison_plot(
            match_baselines(runs),
            compare_policies(runs, n_resamples=100),
            self.root / "censored.png",
        )
        import json

        from analysis.writeup import write_summary

        write_summary(
            self.root,
            runs,
            {
                "runs": len(runs),
                "unobserved_planned_cells": 0,
                "bootstrap_seed": 562,
                "resamples": 100,
                "comparisons": json.loads(
                    compare_policies(runs, n_resamples=100).to_json(orient="records")
                ),
            },
        )
        self.assertIn(
            "added on-time p99 unavailable", (self.root / "diagnostic_summary.txt").read_text()
        )
