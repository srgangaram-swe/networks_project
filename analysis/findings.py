"""Write measured point estimates and explicit limits next to the machine-readable results."""

from pathlib import Path


def _number(value):
    return "unavailable" if value is None else f"{value:.4g}"


def write_findings(output: Path, runs, report):
    simulated = report["measurement_kind"] == "simulation"
    lines = ["Insights", ""]
    if simulated:
        lines += [
            "SIMULATED DATA. These rows come from a toy queue model for software testing.",
            "The assumed policy parameters are not measurements of Linux queue behavior.",
            "",
        ]
    for row in report["comparisons"]:
        lines.append(
            f"{row['policy']}, {row['requested_mbps']:g} Mb/s and {row['flows']} flow(s): "
            f"added p99 {_number(row['added_p99_ms'])} ms; "
            f"goodput retained {_number(row['goodput_retention_pct'])}%; "
            f"interval status {row['interval_status']}."
        )
    lines += [
        "",
        "Findings",
        "",
        f"{len(runs)} runs retain {int(runs.scheduled.sum()):,} scheduled slots, "
        f"including {int(runs.not_sent.sum()):,} unsent slots "
        f"and {int(runs.timeout_count.sum()):,} timeout/late outcomes.",
        "Unsent slots describe generator omissions. "
        "They are not estimates of transport packet loss.",
    ]
    for group in report["ml"]["groups"]:
        if group["status"] == "exploratory_fit":
            for method, quality in group["diagnostics"]["partitions"].items():
                lines.append(
                    f"{method}, {group['requested_mbps']:g} Mb/s/{group['flows']} flow(s): "
                    f"cluster count {quality['clusters']}, noise runs {quality['noise_runs']}, "
                    f"silhouette {_number(quality['silhouette'])}."
                )
    regression = report["regression"]
    lines += [
        f"Ridge/Lasso status: {regression['status']}; {regression['blocks']} recorded blocks."
    ]
    for name, model in regression.get("models", {}).items():
        lines.append(
            f"{name}: held-out-block MAE {model['mae_ms']:.4g} ms, RMSE {model['rmse_ms']:.4g} ms, "
            f"R2 {model['r2']:.4g}; "
            f"training-mean baseline MAE {model['mean_baseline_mae_ms']:.4g} ms."
        )
    lines += [
        "",
        "Conclusions",
        "",
        "Read latency, goodput, delivery outcomes, and uncertainty together. "
        "A low on-time p99 alone does not establish a successful treatment.",
        "K-means and agglomerative clustering use two groups. "
        "DBSCAN can mark noise or find a different number of groups. "
        "No run is excluded automatically.",
        "PCA and t-SNE are views of the fitted features, not additional clustering algorithms. "
        "Internal cluster scores measure geometry, not prediction accuracy.",
        "Ridge and Lasso use only design features. Whole blocks are held out, "
        "with scaling and alpha selection fitted inside the training folds. "
        "This evaluates interpolation among the observed designs.",
        "Finish device setup, timing and calibration checks, protocol review, "
        "and primary collection before drawing conclusions about the physical experiment.",
    ]
    if simulated:
        lines.append(
            "More simulated rows exercise the pipeline; "
            "they do not strengthen evidence about physical queue policies."
        )
    with (output / "insights.txt").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
