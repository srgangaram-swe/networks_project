"""Held-out model predictions and descriptive full-data coefficients."""

import pandas as pd
import seaborn as sns
from matplotlib.lines import Line2D

from analysis.plots.style import COLORS, LABELS, MARKERS, POLICIES, figure_grid, footer, save_figure


def prediction_plot(predictions, model, destination):
    fig, axes, key = figure_grid(
        1, 2, "Ridge and Lasso: predictions for held-out blocks", height=3.8
    )
    if model.get("status") != "exploratory_fit":
        return _unavailable(fig, axes, key, model, destination, predictions)
    for axis, name in zip(axes, ("ridge", "lasso"), strict=True):
        rows = predictions[predictions.model == name]
        sns.scatterplot(
            data=rows,
            x="observed_ms",
            y="predicted_ms",
            hue="policy",
            style="policy",
            palette=COLORS,
            markers=MARKERS,
            hue_order=list(POLICIES),
            style_order=list(POLICIES),
            s=65,
            legend=False,
            ax=axis,
        )
        lower = min(rows.observed_ms.min(), rows.predicted_ms.min())
        upper = max(rows.observed_ms.max(), rows.predicted_ms.max())
        axis.plot([lower, upper], [lower, upper], linestyle="--", color="#6C7885", linewidth=1)
        quality = model["models"][name]
        axis.set(
            xlabel="Observed added p99 (ms)",
            ylabel="Held-out prediction (ms)",
            title=(
                f"{name.title()}: MAE {quality['mae_ms']:.3g} ms\n"
                f"{len(rows)} predictions from {model['blocks']} blocks"
            ),
        )
    handles = [
        Line2D([], [], marker=MARKERS[p], color="none", markerfacecolor=COLORS[p], label=LABELS[p])
        for p in POLICIES
    ]
    footer(
        key,
        "Every point is predicted by a model that did not see that run's block or baseline.\n"
        "Scaling and alpha selection use training blocks only. Dashed lines: exact predictions.\n"
        "This is design interpolation; simulated inputs demonstrate software behavior only.",
        handles,
    )
    return save_figure(
        fig,
        destination,
        measurement_kind=predictions.attrs.get("measurement_kind"),
        transport=predictions.attrs.get("transport", "udp"),
    )


def coefficient_plot(predictions, model, destination):
    fig, axes, key = figure_grid(1, 2, "Regularization: the fitted design coefficients", height=3.8)
    if model.get("status") != "exploratory_fit":
        return _unavailable(fig, axes, key, model, destination, predictions)
    for axis, name in zip(axes, ("ridge", "lasso"), strict=True):
        details = model["models"][name]
        coefficients = details["full_data_coefficients_per_feature_sd"]
        frame = pd.DataFrame(
            {"feature": list(coefficients), "coefficient": list(coefficients.values())}
        )
        frame["feature"] = (
            frame.feature.str.replace("policy__policy_", "")
            .str.replace("numeric__", "")
            .str.replace("_", " ")
        )
        sns.barplot(
            data=frame,
            x="coefficient",
            y="feature",
            color="#0072B2" if name == "ridge" else "#009E73",
            ax=axis,
            errorbar=None,
        )
        axis.axvline(0, color="#6C7885", linewidth=1)
        axis.set(
            xlabel="Added-p99 coefficient per feature SD (ms)",
            ylabel="",
            title=f"{name.title()}; alpha={details['full_data_alpha']:g}",
        )
    footer(
        key,
        "Full-data descriptive fits. Category indicators use FIFO as their reference.\n"
        "All encoded features are standardized; constant features have zero coefficients.\n"
        "These coefficients are not causal effects. Prediction errors come from held-out blocks.",
    )
    return save_figure(
        fig,
        destination,
        measurement_kind=predictions.attrs.get("measurement_kind"),
        transport=predictions.attrs.get("transport", "udp"),
    )


def _unavailable(fig, axes, key, model, destination, predictions):
    for axis, name in zip(axes, ("Ridge", "Lasso"), strict=True):
        axis.set_axis_off()
        axis.set_title(name)
        axis.text(
            0.5, 0.6, "No validated fit for this input", transform=axis.transAxes, ha="center"
        )
        axis.text(
            0.5,
            0.4,
            f"{model.get('blocks', 0)} blocks; at least six required",
            transform=axis.transAxes,
            ha="center",
        )
    footer(
        key,
        "No prediction or coefficient is invented when data are insufficient.\n"
        f"Status: {model.get('status', 'unavailable')}\n"
        "Use independent blocks and complete target measurements before fitting.",
    )
    return save_figure(
        fig,
        destination,
        measurement_kind=predictions.attrs.get("measurement_kind"),
        transport=predictions.attrs.get("transport", "udp"),
    )


def runtime_plot(timings, destination, measurement_kind=None, transport="udp"):
    rows = [
        {
            "stage": row["stage"].replace("_", " "),
            "wall": row["wall_seconds"],
            "CPU": row["process_cpu_seconds"],
        }
        for row in timings
        if row["state"] == "completed"
    ]
    fig, axes, key = figure_grid(1, 1, "Where analysis time is spent", width=10, height=3.5)
    if rows:
        data = pd.DataFrame(rows).melt(id_vars="stage", var_name="clock", value_name="seconds")
        sns.barplot(
            data=data,
            x="seconds",
            y="stage",
            hue="clock",
            palette={"wall": "#0072B2", "CPU": "#D89000"},
            ax=axes[0],
            errorbar=None,
            legend=False,
        )
    else:
        axes[0].text(
            0.5, 0.5, "Stage timings unavailable", ha="center", transform=axes[0].transAxes
        )
        axes[0].set_axis_off()
    from matplotlib.patches import Patch

    footer(
        key,
        "Completed compute stages only; rendering is excluded from this chart.\n"
        "Wall time uses a monotonic clock. CPU time belongs to this analysis process.\n"
        "The full pipeline log separately records collection, export, and worker timings.",
        [
            Patch(color="#0072B2", label="Elapsed wall time"),
            Patch(color="#D89000", label="Process CPU time"),
        ],
    )
    return save_figure(fig, destination, measurement_kind=measurement_kind, transport=transport)
