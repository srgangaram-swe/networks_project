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
V3_TABLE_FILES = TABLE_FILES | {
    "regression_predictions.csv",
    "cluster_diagnostics.csv",
    "insights.txt",
    "analysis_timings.json",
}
V3_EXTRA_PLOTS = ("ridge_lasso_predictions", "ridge_lasso_coefficients", "analysis_runtime")
V3_CLUSTER_PLOTS = ("run_clusters_agglomerative", "run_clusters_dbscan")


def expected_artifacts(report: dict) -> frozenset[str]:
    version = report.get("plot_bundle_version", 1)
    if type(version) is not int or version not in (1, 2, 3):
        raise ValueError("unsupported plot bundle version")
    if version == 1:
        return TABLE_FILES | {f"{name}.png" for name in STATISTICAL_PLOTS[:1] + CLUSTER_PLOTS[:2]}
    tables = V3_TABLE_FILES if version == 3 else TABLE_FILES
    if report["plots_requested"] is False:
        return tables
    names = STATISTICAL_PLOTS + (V3_EXTRA_PLOTS if version == 3 else ())
    if any(group["status"] == "exploratory_fit" for group in report["ml"]["groups"]):
        names += CLUSTER_PLOTS
        if version == 3:
            names += V3_CLUSTER_PLOTS
    return tables | {f"plots/{name}.{extension}" for name in names for extension in ("png", "svg")}
