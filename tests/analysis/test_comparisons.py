import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.utils.compare_policies import compare_policies
from analysis.utils.load_data import load_data
from analysis.utils.match_baselines import match_baselines
from analysis.utils.summarize_runs import summarize_runs
from tests.analysis.support import fixture


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = fixture(Path(self.temp.name) / "export")
        self.runs, _, _ = load_data(self.path)

    def test_hand_computable_paired_reduction_and_retention(self):
        result = compare_policies(self.runs, n_resamples=100).set_index("policy")
        fq = result.loc["fq_codel"]
        self.assertAlmostEqual(fq.p99_reduction_pct, 60)
        self.assertAlmostEqual(fq.goodput_retention_pct, 95)
        self.assertAlmostEqual(fq.p99_reduction_pct_ci_lower, 60)
        self.assertAlmostEqual(fq.p99_reduction_pct_ci_upper, 60)
        self.assertTrue(fq.point_targets_met)
        self.assertFalse(fq.eligible_for_primary)
        self.assertAlmostEqual(result.loc["fifo"].p99_reduction_pct_ci_upper, 0)
        self.assertAlmostEqual(result.loc["fifo"].goodput_retention_pct_ci_lower, 100)
        self.assertTrue(summarize_runs(self.runs).notna().all().all())
        permuted = compare_policies(self.runs.sample(frac=1, random_state=3), n_resamples=100)
        pd.testing.assert_frame_equal(result.reset_index(), permuted)

    def test_independent_exhaustive_block_reference(self):
        import itertools

        matched = match_baselines(self.runs)
        fifo = matched[matched.policy == "fifo"].sort_values("block")
        values = fifo.added_p99_ms.to_list()
        means = [sum(sample) / len(sample) for sample in itertools.product(values, repeat=3)]
        result = compare_policies(self.runs, n_resamples=10000).set_index("policy").loc["fifo"]
        np.testing.assert_allclose(
            [result.added_p99_ms_ci_lower, result.added_p99_ms_ci_upper],
            np.quantile(means, [0.025, 0.975], method="inverted_cdf"),
        )

    def test_missing_and_duplicate_baselines_and_unpaired_fifo_fail(self):
        for frame in (
            self.runs.iloc[1:],
            pd.concat([self.runs, self.runs.iloc[:1]]),
            self.runs[self.runs.policy != "fifo"],
            self.runs[self.runs.flows > 0],
            self.runs[self.runs.flows == 0],
        ):
            with self.assertRaises(ValueError):
                compare_policies(frame, n_resamples=100)
        loaded = self.runs[self.runs.flows > 0].index[-1]
        with self.assertRaises(ValueError):
            compare_policies(self.runs.drop(loaded), n_resamples=100)

    def test_unavailable_quantiles_and_nonpositive_denominators_are_not_filtered(self):
        changed = self.runs.copy()
        changed.loc[changed.flows > 0, "p99_censored"] = True
        result = compare_policies(changed, n_resamples=100)
        self.assertTrue(result.added_p99_ms.isna().all())
        self.assertTrue(result.p99_reduction_pct.isna().all())
        self.assertTrue(result.point_targets_met.isna().all())
        changed = self.runs.copy()
        changed.loc[changed.flows > 0, "p99_ms"] = 0
        changed.loc[changed.policy == "fifo", "goodput_mbps"] = 0
        result = compare_policies(changed, n_resamples=100)
        self.assertTrue(result.p99_reduction_pct.isna().all())
        self.assertTrue(result.goodput_retention_pct.isna().all())

    def test_two_blocks_keep_points_without_spurious_intervals(self):
        result = compare_policies(self.runs[~self.runs.block.str.endswith(":3")], n_resamples=100)
        self.assertTrue(result.added_p99_ms_ci_lower.isna().all())
        self.assertTrue(result.interval_status.eq("insufficient_blocks").all())

    def test_option_bounds(self):
        for options in (
            {"confidence": 1},
            {"n_resamples": True},
            {"n_resamples": 10001},
            {"random_state": None},
            {"random_state": -1},
        ):
            with self.assertRaises(ValueError):
                compare_policies(self.runs, **options)
