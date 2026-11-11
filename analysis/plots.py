"""Plots retain individual runs, missing intervals, and exploratory ML labels."""

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


def comparison_plot(matched, comparisons, destination: Path) -> None:
    conditions = list(comparisons.groupby(["requested_mbps", "flows"], sort=True))
    sns.set_theme(style="whitegrid", context="notebook")
    fig, axes = plt.subplots(len(conditions), 3, figsize=(15, 4 * len(conditions)), squeeze=False)
    specifications = (
        ("added_p99_ms", "Added on-time p99 (ms)"),
        ("goodput_retention_pct", "Goodput retained vs FIFO (%)"),
        ("p99_reduction_pct", "Added-p99 reduction vs FIFO (%)"),
    )
    for panels, ((load, flows), results) in zip(axes, conditions, strict=True):
        results = results.sort_values("policy")
        names = results["policy"].tolist()
        for axis, (metric, label) in zip(panels, specifications, strict=True):
            for index, row in enumerate(results.to_dict("records")):
                value = row[metric]
                if pd.isna(value):
                    axis.text(
                        index,
                        0.5,
                        "unavailable",
                        rotation=90,
                        transform=axis.get_xaxis_transform(),
                        ha="center",
                    )
                    continue
                axis.scatter(index, value, color="#0072B2", s=40)
                lower, upper = row[f"{metric}_ci_lower"], row[f"{metric}_ci_upper"]
                if pd.notna(lower) and pd.notna(upper):
                    axis.vlines(index, lower, upper, color="#0072B2", linewidth=2)
            if metric == "added_p99_ms":
                observed = matched[
                    (matched["requested_mbps"] == load) & (matched["flows"] == flows)
                ]
                sns.stripplot(
                    data=observed,
                    x="policy",
                    y=metric,
                    order=names,
                    ax=axis,
                    color=".4",
                    alpha=0.6,
                    jitter=False,
                    size=4,
                )
            axis.set(
                xticks=range(len(names)),
                xticklabels=names,
                ylabel=label,
                xlabel="",
                title=(
                    f"{load:g} Mb/s requested, {int(flows)} flow(s)\n"
                    f"{int(results['blocks'].min())} paired blocks per policy"
                ),
            )
            axis.tick_params(axis="x", rotation=25)
            axis.axhline(90 if metric == "goodput_retention_pct" else 0, color=".5", linestyle=":")
    fig.suptitle("Diagnostic policy comparisons: paired blocks", fontsize=17)
    fig.text(
        0.03,
        0.025,
        "Points: paired-block means; bars: seeded 95% intervals with at least 3 blocks.\n"
        "Gray points: every matched run. Missing intervals are not zero uncertainty.\n"
        "Primary collection remains unapproved. On-time quantiles can be censored; see the report.",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0.13, 1, 0.95))
    _save(fig, destination)


def clustering_plot(assignments, destination: Path, projection: str = "pca") -> None:
    if assignments.empty:
        return
    conditions = list(assignments.groupby(["requested_mbps", "flows"], sort=True))
    columns = min(2, len(conditions))
    rows = math.ceil(len(conditions) / columns)
    height = 5 * rows + 1
    fig, axes = plt.subplots(rows, columns, figsize=(7 * columns, height), squeeze=False)
    x, y = ("pc1", "pc2") if projection == "pca" else ("tsne1", "tsne2")
    display = "PCA" if projection == "pca" else "t-SNE"
    for axis, ((load, flows), rows) in zip(axes.flat, conditions, strict=False):
        sns.scatterplot(
            data=rows,
            x=x,
            y=y,
            hue="cluster",
            style="policy",
            palette="colorblind",
            s=90,
            ax=axis,
        )
        axis.set(
            title=f"{load:g} Mb/s, {int(flows)} flow(s); n={len(rows)}",
            xlabel=f"{display} dimension 1",
            ylabel=f"{display} dimension 2",
        )
    for axis in list(axes.flat)[len(conditions) :]:
        axis.set_visible(False)
    fig.suptitle(f"{display}: exploratory run profiles", fontsize=16)
    fig.text(
        0.03,
        0.025,
        "Policy labels are for interpretation and are not model features.\n"
        "Clusters are fitted in the six standardized metrics, not the 2D projection.\n"
        "t-SNE distances and separated groups do not establish global structure or effects.\n"
        "No held-out prediction, causal claim, or automatic run exclusion.",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 1.1 / height, 1, 1 - 0.4 / height))
    _save(fig, destination)


def _save(fig, destination):
    try:
        with destination.open("xb") as stream:
            fig.savefig(stream, format="png", dpi=180)
    finally:
        plt.close(fig)
