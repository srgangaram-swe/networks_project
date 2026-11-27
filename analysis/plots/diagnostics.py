"""Delivery accounting and per-run RTT quantiles from validated summaries."""

import math

import numpy as np
import seaborn as sns
from matplotlib.patches import Patch

from analysis.plots.style import LABELS, POLICIES, condition, figure_grid, footer, save_figure


def request_outcome_plot(runs, destination):
    groups = list(runs.groupby(["requested_mbps", "flows"], sort=True))
    columns = min(2, len(groups))
    fig, axes, key = figure_grid(
        math.ceil(len(groups) / columns),
        columns,
        "Delivery accounting: keep generator omissions visible",
        height=3.4,
    )
    specifications = (
        ("on_time", "On-time reply", "#387C91"),
        ("not_sent", "Not sent", "#E0A21B"),
        ("timeout_count", "Timeout or late", "#C65D36"),
    )
    for axis, ((load, flows), rows) in zip(axes, groups, strict=False):
        policies = [p for p in POLICIES if p in set(rows.policy)]
        totals = (
            rows.groupby("policy")[["scheduled", "on_time", "not_sent", "timeout_count"]]
            .sum()
            .loc[policies]
        )
        left = np.zeros(len(totals))
        for metric, _, color in specifications:
            widths = 100 * totals[metric].to_numpy() / totals.scheduled.to_numpy()
            axis.barh(
                range(len(totals)), widths, left=left, height=0.62, color=color, edgecolor="white"
            )
            left += widths
        for index, policy in enumerate(policies):
            rate = 100 * totals.loc[policy, "not_sent"] / totals.loc[policy, "scheduled"]
            axis.text(101, index, f"{rate:.2f}% unsent", va="center", fontsize=10)
        labels = [f"{LABELS[p]}\nn={int(totals.loc[p, 'scheduled']):,} slots" for p in policies]
        axis.set(
            yticks=range(len(policies)),
            yticklabels=labels,
            xlim=(0, 132),
            ylim=(len(policies) - 0.5, -0.6),
            xlabel="Percent of scheduled requests",
            title=condition(load, flows),
        )
        axis.set_xticks([0, 25, 50, 75, 100])
        axis.grid(axis="y", visible=False)
    for axis in axes[len(groups) :]:
        axis.set_visible(False)
    footer(
        key,
        "Every measurement slot is accounted for. Timeout and late outcomes are combined.\n"
        "Unsent slots are generator omissions, not estimates of network packet loss.\n"
        "Counts describe these runs; requests are not independent replications.",
        [Patch(facecolor=color, label=label) for _, label, color in specifications],
    )
    return save_figure(
        fig,
        destination,
        measurement_kind=runs.attrs.get("measurement_kind"),
        transport=runs.attrs.get("transport", "udp"),
    )


def tail_quantile_plot(runs, destination):
    groups = list(runs.groupby(["requested_mbps", "flows"], sort=True))
    columns = min(2, len(groups))
    fig, axes, key = figure_grid(
        math.ceil(len(groups) / columns),
        columns,
        "How the RTT percentiles change under load",
        height=3.3,
    )
    metrics = ["p50_ms", "p95_ms", "p99_ms", "p999_ms"]
    finite = runs[metrics].to_numpy(float)
    lower, upper = (
        (float(np.nanmin(finite)), float(np.nanmax(finite)))
        if np.isfinite(finite).any()
        else (0, 1)
    )
    for axis, ((load, flows), rows) in zip(axes, groups, strict=False):
        policies = [p for p in POLICIES if p in set(rows.policy)]
        values = rows.groupby("policy")[metrics].mean().loc[policies]
        if not values.notna().any().any():
            axis.text(0.5, 0.5, "No on-time RTT quantiles", ha="center", transform=axis.transAxes)
            continue
        sns.heatmap(
            values,
            ax=axis,
            annot=True,
            fmt=".3f",
            cmap="YlGnBu",
            vmin=lower,
            vmax=upper,
            xticklabels=["p50", "p95", "p99", "p99.9"],
            yticklabels=[LABELS[p] for p in policies],
            linewidths=1,
            linecolor="white",
            cbar_kws={"label": "On-time RTT (ms)"},
        )
        for row, col in zip(*np.where(values.isna()), strict=True):
            axis.text(col + 0.5, row + 0.5, "n/a", ha="center", va="center")
        axis.set(
            title=(
                f"{condition(load, flows)}; "
                f"{int(rows.groupby('policy').size().min())} run(s)/policy"
            ),
            xlabel="",
            ylabel="",
        )
    for axis in axes[len(groups) :]:
        axis.set_visible(False)
    footer(
        key,
        "Cells are means of per-run on-time RTT quantiles, not quantiles of pooled requests.\n"
        "Shared color scale. See the delivery plot for omissions and timeouts.\n"
        "High percentiles from a small pilot are descriptive. Primary collection is unapproved.",
    )
    return save_figure(
        fig,
        destination,
        measurement_kind=runs.attrs.get("measurement_kind"),
        transport=runs.attrs.get("transport", "udp"),
    )
