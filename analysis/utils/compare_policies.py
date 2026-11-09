from pathlib import Path
import json
import hashlib
import argparse
import sys
import pandas as pd
import numpy as np

import numpy as np
import pandas as pd


def compare_policies(
    summaries,
    fifo_policy="FIFO",
    confidence=0.95,
    n_resamples=10000,
    random_state=42,
):
    """
    Compare each queue-management policy against FIFO.

    For each policy, load level, and flow count, calculate:
      - Added p99 latency
      - Percentage reduction in added p99 latency vs. FIFO
      - Mean TCP goodput
      - Goodput retention vs. FIFO
      - Bootstrap confidence intervals for these metrics

    Baseline runs are selected by policy. Baseline rows are expected
    to have requested_mbps == 0 and may have flows == 0.

    Bootstrap sampling uses runs as the replication units, not
    individual foreground requests.

    Parameters
    ----------
    summaries : pandas.DataFrame
        Run-level summary data.
    fifo_policy : str
        Name of the FIFO policy used as the comparison baseline.
    confidence : float
        Confidence level for bootstrap intervals.
    n_resamples : int
        Number of bootstrap resamples.
    random_state : int or None
        Random seed for reproducibility.

    Returns
    -------
    pandas.DataFrame
        One row per policy, load level, and flow count.
    """

    required_columns = {
        "policy",
        "requested_mbps",
        "flows",
        "p99_ms",
        "goodput_mbps",
    }

    missing_columns = required_columns - set(summaries.columns)

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {sorted(missing_columns)}"
        )

    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1.")

    if n_resamples < 1:
        raise ValueError("n_resamples must be at least 1.")

    rng = np.random.default_rng(random_state)

    # Separate loaded runs from unloaded baseline runs.
    loaded = summaries[summaries["requested_mbps"] > 0].copy()
    baselines = summaries[summaries["requested_mbps"] == 0].copy()

    if loaded.empty:
        raise ValueError("No loaded runs found.")

    if baselines.empty:
        raise ValueError("No baseline runs found.")

    policies = loaded["policy"].dropna().unique()

    if fifo_policy not in policies:
        raise ValueError(
            f"FIFO policy '{fifo_policy}' not found in loaded runs."
        )

    # Convert measurements to numeric values and remove invalid rows.
    loaded["p99_ms"] = pd.to_numeric(
        loaded["p99_ms"], errors="coerce"
    )
    loaded["goodput_mbps"] = pd.to_numeric(
        loaded["goodput_mbps"], errors="coerce"
    )

    baselines["p99_ms"] = pd.to_numeric(
        baselines["p99_ms"], errors="coerce"
    )

    loaded = loaded.dropna(
        subset=["policy", "requested_mbps", "flows",
                "p99_ms", "goodput_mbps"]
    )

    baselines = baselines.dropna(
        subset=["policy", "p99_ms"]
    )

    if loaded.empty or baselines.empty:
        raise ValueError("No valid loaded runs or baseline runs found.")

    alpha = 1 - confidence

    def bootstrap_means(values):
        """Generate bootstrap samples of the mean of run-level values."""
        values = np.asarray(values, dtype=float)
        values = values[np.isfinite(values)]

        if len(values) == 0:
            raise ValueError("Cannot bootstrap an empty sample.")

        indices = rng.integers(
            0,
            len(values),
            size=(n_resamples, len(values)),
        )

        return values[indices].mean(axis=1)

    def confidence_interval(samples):
        """Return a percentile bootstrap confidence interval."""
        samples = np.asarray(samples, dtype=float)
        samples = samples[np.isfinite(samples)]

        if len(samples) == 0:
            return np.nan, np.nan

        lower = np.percentile(samples, 100 * alpha / 2)
        upper = np.percentile(samples, 100 * (1 - alpha / 2))

        return lower, upper

    results = []

    # Compare policies under equivalent load and flow conditions.
    conditions = loaded[
        ["requested_mbps", "flows"]
    ].drop_duplicates()

    for _, condition in conditions.iterrows():

        load = condition["requested_mbps"]
        flow_count = condition["flows"]

        fifo_runs = loaded[
            (loaded["policy"] == fifo_policy)
            & (loaded["requested_mbps"] == load)
            & (loaded["flows"] == flow_count)
        ]

        if fifo_runs.empty:
            raise ValueError(
                f"No FIFO runs found for load={load}, "
                f"flows={flow_count}."
            )

        fifo_baseline = baselines[
            baselines["policy"] == fifo_policy
        ]

        if fifo_baseline.empty:
            raise ValueError(
                f"No baseline found for policy '{fifo_policy}'."
            )

        fifo_loaded_p99 = fifo_runs["p99_ms"].to_numpy(dtype=float)
        fifo_baseline_p99 = fifo_baseline["p99_ms"].to_numpy(dtype=float)

        fifo_added_samples = (
            bootstrap_means(fifo_loaded_p99)
            - bootstrap_means(fifo_baseline_p99)
        )

        fifo_added_p99 = (
            fifo_runs["p99_ms"].mean()
            - fifo_baseline["p99_ms"].mean()
        )

        fifo_goodput_samples = bootstrap_means(
            fifo_runs["goodput_mbps"].to_numpy(dtype=float)
        )

        fifo_goodput = fifo_runs["goodput_mbps"].mean()

        for policy in policies:

            policy_runs = loaded[
                (loaded["policy"] == policy)
                & (loaded["requested_mbps"] == load)
                & (loaded["flows"] == flow_count)
            ]

            if policy_runs.empty:
                continue

            # Important: baseline runs have flows == 0, so do not
            # filter baselines by flow_count.
            policy_baseline = baselines[
                baselines["policy"] == policy
            ]

            if policy_baseline.empty:
                raise ValueError(
                    f"No baseline found for policy '{policy}'."
                )

            policy_loaded_p99 = policy_runs[
                "p99_ms"
            ].to_numpy(dtype=float)

            policy_baseline_p99 = policy_baseline[
                "p99_ms"
            ].to_numpy(dtype=float)

            # Calculate the policy's added p99 latency.
            added_p99 = (
                policy_runs["p99_ms"].mean()
                - policy_baseline["p99_ms"].mean()
            )

            # Bootstrap the loaded and baseline runs independently.
            policy_added_samples = (
                bootstrap_means(policy_loaded_p99)
                - bootstrap_means(policy_baseline_p99)
            )

            added_ci_lower, added_ci_upper = confidence_interval(
                policy_added_samples
            )

            # Calculate percentage reduction relative to FIFO.
            if fifo_added_p99 > 0:
                p99_reduction = (
                    100
                    * (fifo_added_p99 - added_p99)
                    / fifo_added_p99
                )

                # Only calculate percentage reductions for bootstrap
                # samples where FIFO's added latency is positive.
                valid = fifo_added_samples > 0

                reduction_samples = (
                    100
                    * (
                        fifo_added_samples[valid]
                        - policy_added_samples[valid]
                    )
                    / fifo_added_samples[valid]
                )

                reduction_ci_lower, reduction_ci_upper = (
                    confidence_interval(reduction_samples)
                )

            else:
                # Percentage improvement is not meaningful when
                # FIFO's added latency is zero or negative.
                p99_reduction = np.nan
                reduction_ci_lower = np.nan
                reduction_ci_upper = np.nan

            # Calculate goodput retention relative to FIFO.
            policy_goodput = policy_runs["goodput_mbps"].mean()

            if fifo_goodput > 0:
                goodput_retention = (
                    100 * policy_goodput / fifo_goodput
                )

                policy_goodput_samples = bootstrap_means(
                    policy_runs["goodput_mbps"].to_numpy(dtype=float)
                )

                # Compare independently bootstrapped run-level
                # goodput means.
                valid = fifo_goodput_samples > 0

                retention_samples = (
                    100
                    * policy_goodput_samples[valid]
                    / fifo_goodput_samples[valid]
                )

                retention_ci_lower, retention_ci_upper = (
                    confidence_interval(retention_samples)
                )

            else:
                goodput_retention = np.nan
                retention_ci_lower = np.nan
                retention_ci_upper = np.nan

            # Check whether the policy meets both project targets.
            primary_target_met = (
                pd.notna(p99_reduction)
                and pd.notna(goodput_retention)
                and p99_reduction >= 50
                and goodput_retention >= 90
            )

            results.append({
                "policy": policy,
                "requested_mbps": load,
                "flows": flow_count,
                "runs": len(policy_runs),
                "added_p99_ms": added_p99,
                "added_p99_ci_lower": added_ci_lower,
                "added_p99_ci_upper": added_ci_upper,
                "p99_reduction_pct": p99_reduction,
                "reduction_ci_lower": reduction_ci_lower,
                "reduction_ci_upper": reduction_ci_upper,
                "goodput_mbps": policy_goodput,
                "goodput_retention_pct": goodput_retention,
                "retention_ci_lower": retention_ci_lower,
                "retention_ci_upper": retention_ci_upper,
                "primary_target_met": primary_target_met,
            })

    return pd.DataFrame(results)