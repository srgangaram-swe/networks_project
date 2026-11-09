from pathlib import Path
import json
import hashlib
import argparse
import sys
import pandas as pd
import numpy as np



def match_baselines(summaries):
    """
    Compare average loaded-run p99 latency against the average
    unloaded baseline p99 latency for the same number of flows.

    Returns one row per experimental condition.
    """

    required_columns = [
        "policy",
        "requested_mbps",
        "flows",
        "p99_ms",
    ]

    missing = set(required_columns) - set(summaries.columns)

    if missing:
        raise ValueError(
            f"Missing required columns: {sorted(missing)}"
        )

    # Separate loaded runs and unloaded baselines.
    baselines = summaries[
        summaries["requested_mbps"] == 0
    ]


    loaded = summaries[
        summaries["requested_mbps"] > 0
    ]

    # Calculate average baseline p99 for each flow count.
    baseline_stats = (
        baselines
        .groupby("policy")["p99_ms"]
        .agg(["mean", "count"])
        .reset_index()
        .rename(columns={
            "mean": "baseline_p99_ms",
            "count": "baseline_runs",
        })
    )

    print(baseline_stats)

    # Calculate average p99 for each loaded condition.
    loaded_stats = (
        loaded
        .groupby(["policy", "requested_mbps", "flows"])["p99_ms"]
        .agg(["mean", "count"])
        .reset_index()
        .rename(columns={
            "mean": "loaded_p99_ms",
            "count": "loaded_runs",
        })
    )
    print(loaded_stats)

    # Attach the corresponding baseline to each loaded condition.
    matched = loaded_stats.merge(
        baseline_stats,
        on="policy",
        how="left",
        validate="many_to_one",
    )

    # Calculate added p99 latency.
    matched["added_p99_ms"] = (
        matched["loaded_p99_ms"] - matched["baseline_p99_ms"]
    )

    return matched