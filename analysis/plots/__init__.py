"""Plotting entry points and a reproducible preliminary figure gallery."""

import pandas as pd

from analysis.plots.clusters import cluster_metrics_plot, cluster_profile_plot, clustering_plot
from analysis.plots.comparisons import comparison_plot
from analysis.plots.diagnostics import request_outcome_plot, tail_quantile_plot
from analysis.plots.models import coefficient_plot, prediction_plot, runtime_plot

__all__ = ["comparison_plot", "clustering_plot", "render_plots"]


def render_plots(
    runs,
    matched,
    comparisons,
    assignments,
    model,
    directory,
    *,
    predictions=None,
    regression=None,
    timings=(),
):
    predictions = predictions if predictions is not None else pd.DataFrame()
    regression = regression if regression is not None else {}
    directory.mkdir()
    results = {
        "policy_comparisons": comparison_plot(
            matched, comparisons, directory / "policy_comparisons.png"
        ),
        "request_outcomes": request_outcome_plot(runs, directory / "request_outcomes.png"),
        "tail_quantiles": tail_quantile_plot(runs, directory / "tail_quantiles.png"),
        "ridge_lasso_predictions": prediction_plot(
            predictions, regression, directory / "ridge_lasso_predictions.png"
        ),
        "ridge_lasso_coefficients": coefficient_plot(
            predictions, regression, directory / "ridge_lasso_coefficients.png"
        ),
        "analysis_runtime": runtime_plot(
            timings,
            directory / "analysis_runtime.png",
            runs.attrs.get("measurement_kind"),
            runs.attrs.get("transport", "udp"),
        ),
    }
    if not assignments.empty:
        results.update(
            {
                "run_clusters": clustering_plot(assignments, directory / "run_clusters.png"),
                "run_clusters_tsne": clustering_plot(
                    assignments, directory / "run_clusters_tsne.png", "tsne"
                ),
                "run_clusters_metrics": cluster_metrics_plot(
                    runs, assignments, directory / "run_clusters_metrics.png"
                ),
                "cluster_profiles": cluster_profile_plot(
                    assignments, model, directory / "cluster_profiles.png"
                ),
                "run_clusters_agglomerative": clustering_plot(
                    assignments,
                    directory / "run_clusters_agglomerative.png",
                    method="agglomerative",
                ),
                "run_clusters_dbscan": clustering_plot(
                    assignments, directory / "run_clusters_dbscan.png", method="dbscan"
                ),
            }
        )
    return results
