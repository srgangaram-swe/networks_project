"""Show fitted assignments without interpreting projections as causal evidence."""

import math

import numpy as np
import pandas as pd
import seaborn as sns

from analysis.plots.style import (
    CLUSTERS,
    LABELS,
    MARKERS,
    POLICIES,
    cluster_key,
    condition,
    figure_grid,
    footer,
    save_figure,
)


def clustering_plot(assignments, destination, projection="pca"):
    if assignments.empty:
        return None
    x, y = ("pc1", "pc2") if projection == "pca" else ("tsne1", "tsne2")
    name = "PCA" if projection == "pca" else "t-SNE"
    return _scatter(
        assignments,
        destination,
        f"{name}: the fitted run clusters",
        x,
        y,
        f"{name} dimension 1",
        f"{name} dimension 2",
    )


def cluster_metrics_plot(runs, assignments, destination):
    if assignments.empty:
        return None
    values = assignments.merge(
        runs[["run_id", "p99_ms", "goodput_mbps"]], on="run_id", validate="one_to_one"
    )
    return _scatter(
        values,
        destination,
        "The same clusters in measured latency and goodput",
        "goodput_mbps",
        "p99_ms",
        "TCP receiver goodput (Mb/s)",
        "On-time RTT p99 (ms)",
    )


def _scatter(data, destination, title, x, y, xlabel, ylabel):
    groups = list(data.groupby(["requested_mbps", "flows"], sort=True))
    columns = min(2, len(groups))
    fig, axes, key = figure_grid(
        math.ceil(len(groups) / columns), columns, title, width=12 if columns > 1 else 9, height=3.8
    )
    for axis, ((load, flows), rows) in zip(axes, groups, strict=False):
        for policy in POLICIES:
            points = rows[rows.policy == policy]
            if points.empty:
                continue
            sns.scatterplot(
                data=points,
                x=x,
                y=y,
                hue="cluster",
                hue_order=[0, 1],
                palette=CLUSTERS,
                marker=MARKERS[policy],
                s=105,
                edgecolor="white",
                linewidth=0.8,
                legend=False,
                ax=axis,
            )
            axis.collections[-1].set_label(policy)
        axis.set(
            xlabel=xlabel, ylabel=ylabel, title=f"{condition(load, flows)}; n={len(rows)} runs"
        )
        axis.margins(x=0.16, y=0.18)
    for axis in axes[len(groups) :]:
        axis.set_visible(False)
    footer(
        key,
        "Each marker is one loaded run. K-means uses six standardized metrics, not this 2D view.\n"
        "Policy names are labels. t-SNE distances do not establish global structure.\n"
        "Available fitted conditions only; no automatic exclusions or predictive validation.",
        cluster_key(),
    )
    return save_figure(fig, destination)


def cluster_profile_plot(assignments, model, destination):
    if assignments.empty:
        return None
    groups = [group for group in model["groups"] if group["status"] == "exploratory_fit"]
    fig, axes, key = figure_grid(len(groups), 2, "What drives the exploratory clusters", height=3.3)
    labels = [
        "RTT\np99",
        "TCP\ngoodput",
        "RTT\njitter",
        "Lag\np99",
        "Timeout\nrate",
        "Unsent\nrate",
    ]
    for index, group in enumerate(groups):
        means = np.asarray(group["standardization_mean"])
        scales = np.asarray(group["standardization_scale"])
        values = (np.asarray(group["centroids_original_units"]) - means) / scales
        limit = max(1, float(abs(values).max()))
        axis = axes[2 * index]
        sns.heatmap(
            values,
            ax=axis,
            annot=True,
            fmt=".2f",
            cmap="vlag",
            center=0,
            vmin=-limit,
            vmax=limit,
            xticklabels=labels,
            yticklabels=["Cluster 0", "Cluster 1"],
            cbar_kws={"label": "Within-condition z score"},
            linewidths=1,
            linecolor="white",
        )
        axis.tick_params(axis="x", labelsize=9, rotation=0)
        axis.set_title(condition(group["requested_mbps"], group["flows"]), loc="left")
        rows = assignments[
            (assignments.requested_mbps == group["requested_mbps"])
            & (assignments.flows == group["flows"])
        ]
        policies = [p for p in POLICIES if p in set(rows.policy)]
        counts = pd.crosstab(rows.policy, rows.cluster).reindex(
            index=policies, columns=[0, 1], fill_value=0
        )
        sns.heatmap(
            counts,
            ax=axes[2 * index + 1],
            annot=True,
            fmt="d",
            cmap="Blues",
            vmin=0,
            xticklabels=["Cluster 0", "Cluster 1"],
            yticklabels=[LABELS[p] for p in policies],
            cbar_kws={"label": "Number of runs"},
            linewidths=1,
            linecolor="white",
        )
        axes[2 * index + 1].set(title=f"Actual assignments; n={len(rows)}", xlabel="", ylabel="")
    footer(
        key,
        "Left: centroids standardized within the condition; zero means average.\n"
        "Right: every fitted run by policy and cluster. Constant features have zero variation.\n"
        "Two clusters were specified in advance. Groups are descriptive, not policy rankings.",
    )
    return save_figure(fig, destination)
