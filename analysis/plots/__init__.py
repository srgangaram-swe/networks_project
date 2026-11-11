"""Plotting entry points and a reproducible preliminary figure gallery."""

from analysis.plots.clusters import cluster_metrics_plot, cluster_profile_plot, clustering_plot
from analysis.plots.comparisons import comparison_plot
from analysis.plots.diagnostics import request_outcome_plot, tail_quantile_plot

__all__ = ["comparison_plot", "clustering_plot", "render_plots"]


def render_plots(runs, matched, comparisons, assignments, model, directory):
    directory.mkdir()
    results = {
        "policy_comparisons": comparison_plot(
            matched, comparisons, directory / "policy_comparisons.png"
        ),
        "request_outcomes": request_outcome_plot(runs, directory / "request_outcomes.png"),
        "tail_quantiles": tail_quantile_plot(runs, directory / "tail_quantiles.png"),
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
            }
        )
    return results
