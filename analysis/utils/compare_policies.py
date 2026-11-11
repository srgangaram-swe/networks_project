"""Seeded percentile bootstrap of complete paired blocks, without ratio filtering."""

import numpy as np
import pandas as pd

from analysis.utils.match_baselines import match_baselines


def _interval(values, confidence):
    if not np.isfinite(values).all():
        return (None, None)
    alpha = (1 - confidence) / 2
    return tuple(float(x) for x in np.quantile(values, [alpha, 1 - alpha]))


def _ratio(numerator, denominator):
    # A nonpositive draw makes the entire ratio interval unavailable. Never
    # condition on favorable draws or truncate negative added latency.
    if not np.isfinite(numerator).all() or not (denominator > 0).all():
        return np.full_like(numerator, np.nan)
    return 100 * numerator / denominator


def _comparison(policy, fifo, indices, confidence):
    added = policy["added_p99_ms"].to_numpy(float)
    reference = fifo["added_p99_ms"].to_numpy(float)
    goodput = policy["goodput_mbps"].to_numpy(float)
    fifo_goodput = fifo["goodput_mbps"].to_numpy(float)
    estimates = {
        "added_p99_ms": np.mean(added),
        "latency_advantage_ms": np.mean(reference - added),
        "p99_reduction_pct": _ratio(
            np.array([np.mean(reference - added)]), np.array([np.mean(reference)])
        )[0],
        "goodput_retention_pct": _ratio(
            np.array([np.mean(goodput)]), np.array([np.mean(fifo_goodput)])
        )[0],
        "goodput_mbps": np.mean(goodput),
    }
    a, f = added[indices].mean(axis=1), reference[indices].mean(axis=1)
    g, fg = goodput[indices].mean(axis=1), fifo_goodput[indices].mean(axis=1)
    samples = {
        "added_p99_ms": a,
        "latency_advantage_ms": f - a,
        "p99_reduction_pct": _ratio(f - a, f),
        "goodput_retention_pct": _ratio(g, fg),
        "goodput_mbps": g,
    }
    result = {}
    for name, estimate in estimates.items():
        low, high = _interval(samples[name], confidence) if len(added) >= 3 else (None, None)
        result.update(
            {
                name: float(estimate) if np.isfinite(estimate) else None,
                f"{name}_ci_lower": low,
                f"{name}_ci_upper": high,
            }
        )
        result[f"{name}_interval_status"] = (
            "insufficient_blocks"
            if len(added) < 3
            else "available"
            if low is not None
            else "undefined_metric_or_nonpositive_reference"
        )
    result["interval_status"] = "available" if len(added) >= 3 else "insufficient_blocks"
    reduction, retention = result["p99_reduction_pct"], result["goodput_retention_pct"]
    result["point_targets_met"] = (
        None if reduction is None or retention is None else reduction >= 50 and retention >= 90
    )
    result["eligible_for_primary"] = False
    return result


def compare_policies(
    summaries, fifo_policy="fifo", confidence=0.95, n_resamples=10000, random_state=562
):
    if not 0 < confidence < 1 or type(n_resamples) is not int or not 100 <= n_resamples <= 10000:
        raise ValueError(
            "confidence must be in (0,1) and resamples must be an integer from 100 to 10000"
        )
    if type(random_state) is not int or not 0 <= random_state < 2**32:
        raise ValueError("an explicit unsigned 32-bit seed is required")
    matched = match_baselines(summaries)
    rng = np.random.default_rng(random_state)
    rows = []
    draws = {}
    for (load, flows), condition in matched.groupby(["requested_mbps", "flows"], sort=True):
        fifo = condition[condition["policy"] == fifo_policy].sort_values("block")
        if fifo.empty:
            raise ValueError("missing FIFO reference for a loaded condition")
        block_key = tuple(fifo["block"])
        if block_key not in draws:
            draws[block_key] = rng.integers(0, len(fifo), size=(n_resamples, len(fifo)))
        indices = draws[block_key]
        for policy, runs in condition.groupby("policy", sort=True):
            runs = runs.sort_values("block")
            if runs["block"].tolist() != fifo["block"].tolist() or runs["block"].duplicated().any():
                raise ValueError("policy and FIFO must have the same complete paired blocks")
            rows.append(
                {
                    "policy": policy,
                    "requested_mbps": load,
                    "flows": flows,
                    "blocks": len(runs),
                    **_comparison(runs, fifo, indices, confidence),
                }
            )
    return pd.DataFrame(rows)
