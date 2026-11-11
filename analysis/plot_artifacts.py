"""Versioned plot paths shared by the analysis runner and its integrity check."""

STATISTICAL_PLOTS = ("policy_comparisons", "request_outcomes", "tail_quantiles")
CLUSTER_PLOTS = ("run_clusters", "run_clusters_tsne", "run_clusters_metrics", "cluster_profiles")
TABLE_FILES = frozenset(
    {
        "runs.csv",
        "matched_baselines.csv",
        "policy_comparisons.csv",
        "run_clusters.csv",
        "run_statistics.csv",
        "diagnostic_summary.txt",
        "writeup_table.tex",
    }
)


def expected_artifacts(report: dict) -> frozenset[str]:
    version = report.get("plot_bundle_version", 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError("unsupported plot bundle version")
    if version == 1:
        return TABLE_FILES | {f"{name}.png" for name in STATISTICAL_PLOTS[:1] + CLUSTER_PLOTS[:2]}
    if report["plots_requested"] is False:
        return TABLE_FILES
    names = STATISTICAL_PLOTS
    if any(group["status"] == "exploratory_fit" for group in report["ml"]["groups"]):
        names += CLUSTER_PLOTS
    return TABLE_FILES | {
        f"plots/{name}.{extension}" for name in names for extension in ("png", "svg")
    }
