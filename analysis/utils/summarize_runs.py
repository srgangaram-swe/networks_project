"""Descriptive summaries keep missing-count columns beside every metric."""

from analysis.utils.validate_data import METRICS, required


def summarize_runs(summaries):
    groups = ["policy", "requested_mbps", "flows"]
    required(summaries, (*groups, *METRICS))
    metrics = [
        *METRICS,
        *[name for name in ("cpu_busy_percent", "cpu_iowait_percent") if name in summaries],
    ]
    return summaries.groupby(groups, sort=True)[metrics].agg(
        ["mean", "median", "std", "count", "size"]
    )
