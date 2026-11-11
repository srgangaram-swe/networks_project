"""Human-readable diagnostic findings and a LaTeX table for later report drafting."""

from pathlib import Path


def _number(value) -> str:
    return "unavailable" if value is None else f"{value:.3f}"


def write_summary(directory: Path, summaries, report: dict) -> None:
    rows = report["comparisons"]
    lines = [
        "Diagnostic experiment summary",
        "",
        f"Observed runs: {report['runs']}. "
        f"Unobserved planned cells: {report['unobserved_planned_cells']}.",
        f"Measured request slots: {int(summaries['scheduled'].sum())}.",
        f"Unsent slots: {int(summaries['not_sent'].sum())}. "
        f"Timeout/late outcomes: {int(summaries['timeout_count'].sum())}.",
        "Primary eligibility: false. These observations require calibration and protocol review.",
        "",
        "Loaded runs use the recorded same-policy, same-block unloaded baseline.",
        f"Intervals use paired blocks, seed {report['bootstrap_seed']}, "
        f"and {report['resamples']} resamples.",
        "Fewer than three blocks has no interval. Unavailable ratios are not zero effects.",
        "",
    ]
    table = [
        r"{\small",
        r"\begin{tabular}{@{}lrrrrr@{}}",
        r"\hline",
        r"Policy & Load & Flows & Blocks & Added p99 & Goodput \\",
        r" & (Mb/s) & & & (ms) & retained (\%) \\",
        r"\hline",
    ]
    for row in rows:
        added, retained = _number(row["added_p99_ms"]), _number(row["goodput_retention_pct"])
        lines.append(
            f"{row['policy']}: {row['requested_mbps']:g} Mb/s requested, "
            f"{int(row['flows'])} flows, "
            f"{row['blocks']} blocks; added on-time p99 {added} ms; "
            f"added-p99 reduction {_number(row['p99_reduction_pct'])}%; "
            f"goodput retained {retained}%."
        )
        policy = row["policy"].replace("_", r"\_")
        table.append(
            f"{policy} & {row['requested_mbps']:g} & {int(row['flows'])} & "
            f"{row['blocks']} & {added} & {retained} " + r"\\"
        )
    table.extend((r"\hline", r"\end{tabular}", "}"))
    lines.extend(
        (
            "",
            "K-means describes standardized run metrics within each load/flow condition.",
            "PCA and t-SNE visualize those metrics; cluster labels are fitted in six dimensions.",
            "This is exploratory analysis, with no held-out prediction or automatic exclusion.",
            "Use report.json for source identities, intervals, model settings, "
            "and artifact hashes.",
            "Keep missed slots, censoring, and unfavorable goodput in the final discussion.",
        )
    )
    (directory / "diagnostic_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (directory / "writeup_table.tex").write_text("\n".join(table) + "\n", encoding="utf-8")
