"""Pair each loaded run with its recorded same-policy, same-block baseline."""

import numpy as np
import pandas as pd

from analysis.utils.validate_data import required


def match_baselines(summaries):
    required(
        summaries,
        (
            "run_id",
            "policy",
            "block",
            "cohort",
            "cell_id",
            "baseline_id",
            "requested_mbps",
            "flows",
            "p99_ms",
            "p99_censored",
        ),
    )
    if summaries.duplicated(["cohort", "cell_id"]).any():
        raise ValueError("duplicate schedule cell across exports")
    baselines = summaries[summaries["flows"] == 0]
    loaded = summaries[summaries["flows"] > 0]
    if loaded.empty or baselines.empty:
        raise ValueError("both loaded runs and recorded unloaded baselines are required")
    rows = []
    lookup = {(row["cohort"], row["cell_id"]): row for row in baselines.to_dict("records")}
    for row in loaded.to_dict("records"):
        base = lookup.get((row["cohort"], row["baseline_id"]))
        if base is None or (base["policy"], base["block"]) != (row["policy"], row["block"]):
            raise ValueError(f"missing same-block baseline for {row['cell_id']}")
        valid = not (row["p99_censored"] or base["p99_censored"])
        added = row["p99_ms"] - base["p99_ms"] if valid else np.nan
        rows.append(
            {
                **row,
                "baseline_run_id": base["run_id"],
                "baseline_p99_ms": base["p99_ms"],
                "added_p99_ms": added,
                "comparison_status": "available" if pd.notna(added) else "censored_or_missing_p99",
            }
        )
    return pd.DataFrame(rows)
