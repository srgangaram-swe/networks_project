"""Shared figure layout with a reserved key and caption band."""

from io import BytesIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.lines import Line2D

POLICIES = ("fifo", "fq_codel", "cake_best_effort", "cake_bounded")
LABELS = {
    "fifo": "FIFO",
    "fq_codel": "FQ-CoDel",
    "cake_best_effort": "CAKE best effort",
    "cake_bounded": "CAKE bounded",
}
MARKERS = {"fifo": "s", "fq_codel": "o", "cake_best_effort": "^", "cake_bounded": "D"}
COLORS = {
    "fifo": "#56616E",
    "fq_codel": "#0072B2",
    "cake_best_effort": "#009E73",
    "cake_bounded": "#8B5FA8",
}
CLUSTERS = {0: "#0072B2", 1: "#D89000"}


def figure_grid(rows: int, columns: int, title: str, *, width=12, height=3.4):
    sns.set_theme(
        style="whitegrid",
        context="notebook",
        rc={
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.labelsize": 11,
            "axes.titlesize": 12,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": "#E4E9EF",
            "grid.linewidth": 0.65,
            "svg.hashsalt": "networks-figures-v2",
        },
    )
    fig = plt.figure(figsize=(width, rows * height + 1.85), layout="constrained")
    grid = fig.add_gridspec(rows + 1, columns, height_ratios=[height] * rows + [1.6])
    axes = [
        fig.add_subplot(grid[row, col], label="data")
        for row in range(rows)
        for col in range(columns)
    ]
    key = fig.add_subplot(grid[-1, :], label="key")
    key.set_axis_off()
    fig.suptitle(title, fontsize=17, fontweight="bold", color="#172B42")
    return fig, axes, key


def footer(key, caption: str, handles=()):
    if handles:
        key.legend(
            handles=handles,
            loc="upper center",
            bbox_to_anchor=(0.5, 1),
            ncol=min(4, len(handles)),
            frameon=False,
            fontsize=10,
            handletextpad=0.5,
        )
    key.text(
        0.01,
        0.43 if handles else 0.8,
        caption,
        va="top",
        fontsize=9.5,
        color="#465569",
        linespacing=1.4,
    )


def cluster_key():
    handles = [
        Line2D(
            [],
            [],
            marker=MARKERS[p],
            color="none",
            markerfacecolor="white",
            markeredgecolor="#273A50",
            markersize=7,
            label=LABELS[p],
        )
        for p in POLICIES
    ]
    handles += [
        Line2D(
            [],
            [],
            marker="o",
            color="none",
            markerfacecolor=color,
            markersize=8,
            label=f"Cluster {label}",
        )
        for label, color in CLUSTERS.items()
    ]
    return handles


def condition(load, flows):
    return (
        "Unloaded baseline" if not flows else f"{load:g} Mb/s requested; {int(flows)} TCP flow(s)"
    )


def _visible_texts(fig):
    texts = list(fig.texts)
    for axis in fig.axes:
        if not axis.get_visible():
            continue
        texts.extend(axis.texts)
        if axis.axison:
            texts.extend([axis.title, axis._left_title, axis._right_title])
            for coordinate in (axis.xaxis, axis.yaxis):
                texts.extend([coordinate.label, coordinate.get_offset_text()])
                lower, upper = sorted(coordinate.get_view_interval())
                for tick in coordinate.get_major_ticks():
                    if lower <= tick.get_loc() <= upper:
                        texts.extend([tick.label1, tick.label2])
        legend = axis.get_legend()
        if legend:
            texts.extend(legend.get_texts())
    return [text for text in texts if text.get_visible() and text.get_text().strip()]


def audit_layout(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    panels = [axis for axis in fig.axes if axis.get_visible() and axis.get_label() == "data"]
    legends = list(fig.legends) + [axis.get_legend() for axis in fig.axes if axis.get_legend()]
    overlaps = sum(
        legend.get_window_extent(renderer).overlaps(axis.get_window_extent(renderer))
        for legend in legends
        for axis in panels
    )
    bounds = fig.bbox
    clipped = []
    for text in _visible_texts(fig):
        box = text.get_window_extent(renderer)
        outside = (
            box.x0 < bounds.x0 - 2
            or box.x1 > bounds.x1 + 2
            or box.y0 < bounds.y0 - 2
            or box.y1 > bounds.y1 + 2
        )
        if outside:
            clipped.append(text.get_text())
    overflow = len(clipped)
    if overlaps or overflow:
        raise ValueError(
            f"figure layout failed: {overlaps} legend overlaps, "
            f"{overflow} clipped text labels: {clipped}"
        )
    return {
        "data_panels": len(panels),
        "legends": len(legends),
        "legend_overlap_count": int(overlaps),
        "text_overflow_count": int(overflow),
        "width_px": int(bounds.width),
        "height_px": int(bounds.height),
    }


def save_figure(fig, destination: Path):
    try:
        result = audit_layout(fig)
        for extension in ("png", "svg"):
            metadata = {
                "Title": fig._suptitle.get_text(),
                "Description": "Diagnostic measurements; not primary evidence.",
            }
            if extension == "svg":
                metadata["Date"] = None
            with destination.with_suffix(f".{extension}").open("xb") as stream:
                with BytesIO() as rendered:
                    fig.savefig(rendered, format=extension, dpi=200, metadata=metadata)
                    payload = rendered.getvalue()
                if extension == "svg":
                    payload = b"\n".join(line.rstrip() for line in payload.splitlines()) + b"\n"
                stream.write(payload)
        return result
    finally:
        plt.close(fig)
