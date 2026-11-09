
from pathlib import Path
import json
import hashlib
import argparse
import sys
import pandas as pd
import numpy as np


def summarize_runs(summaries):
    """
    Calculate descriptive statistics for each experimental condition.

    Groups results by policy, offered load, and TCP flow count.
    """
    group_columns = [
        "policy",
        "requested_mbps",
        "flows",
    ]

    metrics = [
        "p50_ms",
        "p95_ms",
        "p99_ms",
        "goodput_mbps",
        "timeout_rate",
        "not_sent_rate",
    ]

    required_columns = group_columns + metrics

    missing = set(required_columns) - set(summaries.columns)

    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    return (
        summaries
        .groupby(group_columns)[metrics]
        .agg(["mean", "median", "std", "count"])
    )
