"""Paired policy estimates and actual run observations."""

import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

from analysis.plots.style import (
    COLORS,
    LABELS,
    POLICIES,
    condition,
    figure_grid,
    footer,
    save_figure,
)


def comparison_plot(matched, comparisons, destination):
    conditions = list(comparisons.groupby(["requested_mbps", "flows"], sort=True))
    fig, axes, key = figure_grid(len(conditions), 3, "Queue-policy tradeoffs under contention")
    metrics = (
        ("added_p99_ms", "Added on-time p99", "Milliseconds", 0),
        ("goodput_retention_pct", "TCP goodput retained", "Percent of FIFO", 90),
        ("p99_reduction_pct", "Added-p99 reduction", "Percent vs FIFO", 50),
    )
    for number, ((load, flows), results) in enumerate(conditions):
        names = [p for p in POLICIES if p in set(results.policy)]
        rows = results.set_index("policy").loc[names]
        observed = matched[(matched.requested_mbps == load) & (matched.flows == flows)]
        for column, (metric, title, unit, guide) in enumerate(metrics):
            axis = axes[number * 3 + column]
            _estimates(axis, rows, observed, metric)
            axis.axvline(guide, color="#A77B18", linestyle="--", linewidth=1, zorder=0)
            axis.set(
                yticks=range(len(names)),
                yticklabels=[LABELS[p] if not column else "" for p in names],
                xlabel=unit,
                title=title,
                ylim=(len(names) - 0.5, -0.6),
            )
            if not column:
                axis.set_title("")
                axis.set_title(f"{condition(load, flows)}\n{title}", loc="left")
            axis.margins(x=0.22)
            axis.grid(axis="y", visible=False)
    handles = [
        Line2D(
            [], [], marker="D", color="none", markerfacecolor="#0072B2", label="Paired-block mean"
        ),
        Line2D([], [], marker="o", color="none", markerfacecolor="#7C8A99", label="Individual run"),
        Line2D([], [], color="#A77B18", linestyle="--", label="Zero / 90% / 50% guide"),
    ]
    blocks = int(comparisons.blocks.min())
    footer(
        key,
        f"At least {blocks} paired block(s). Gray dots show available matched latency runs.\n"
        "Bars show supported 95% intervals; missing intervals are not zero uncertainty.\n"
        "On-time RTT can be censored. Diagnostic data; check request outcomes too.",
        handles,
    )
    return save_figure(fig, destination)


def _estimates(axis, rows, observed, metric):
    for index, (policy, row) in enumerate(rows.iterrows()):
        if metric == "added_p99_ms":
            values = observed.loc[observed.policy == policy, metric].dropna().to_numpy()
            offsets = np.linspace(-0.09, 0.09, len(values))
            axis.scatter(values, index + offsets, s=24, color="#8996A5", alpha=0.8, zorder=2)
        value = row[metric]
        if pd.isna(value):
            axis.text(0.04, index, "Unavailable", transform=axis.get_yaxis_transform(), va="center")
            continue
        lower, upper = row[f"{metric}_ci_lower"], row[f"{metric}_ci_upper"]
        if pd.notna(lower) and pd.notna(upper):
            axis.hlines(index, lower, upper, color=COLORS[policy], linewidth=2)
        axis.scatter(value, index, marker="D", s=49, color=COLORS[policy], zorder=3)
        axis.annotate(
            f"{value:.3g}",
            (value, index),
            xytext=(6, 7),
            textcoords="offset points",
            color="#273A50",
            fontsize=10,
        )
