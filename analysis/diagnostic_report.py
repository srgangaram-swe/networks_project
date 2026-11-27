"""Separate descriptive reports for real loopback traffic and RPC companion phases."""

import pandas as pd
import seaborn as sns
from matplotlib.ticker import MaxNLocator

from analysis.plots.style import figure_grid, footer, save_figure
from src.artifacts import atomic_json, digest, read_json
from src.bundle_validation import validate_bundle
from src.diagnostics import _write_csv, summarize
from src.rpc_validation import validate_rpc


def analyze_rpc(directories, output):
    """O(R N log N) time, O(N + R) memory for R <= 280 bounded trial bundles."""
    if not 1 <= len(directories) <= 280:
        raise ValueError("RPC analysis needs between 1 and 280 trials")
    rows, inputs = [], []
    for index, directory in enumerate(directories, 1):
        validate_bundle(directory)
        raw = read_json(directory / "rpc.json")
        summary = validate_rpc(raw)
        config = read_json(directory / "configuration.json", 65536)
        bulk = read_json(directory / "rpc-bulk.json")
        rows.append(
            {
                "trial": index,
                "mode": config["mode"],
                "policy": config["policy"],
                "requested_mbps": config["aggregate_bps"] / 1e6,
                "scheduled_calls": raw["scheduled_calls"],
                "admitted_calls": raw["admitted_calls"],
                "skipped_capacity": raw["skipped_capacity"],
                **summary["counts"],
                "p50_ms": summary["p50_ms"],
                "p95_ms": summary["p95_ms"],
                "p99_ms": summary["p99_ms"],
                "retransmissions": summary["retransmissions"],
                "goodput_mbps": bulk["goodput_mbps"],
                "max_start_lag_ms": raw["max_start_lag_ms"],
            }
        )
        inputs.append(
            {
                "trial": index,
                "manifest_sha256": digest(directory / "manifest.json"),
                "rpc_sha256": digest(directory / "rpc.json"),
            }
        )
    if len({row["mode"] for row in rows}) != 1:
        raise ValueError("RPC analysis cannot combine different topologies")
    output.mkdir(mode=0o755)
    _write_csv(output / "rpc-summary.csv", rows)
    frame = pd.DataFrame(rows)
    title = f"RPC call diagnostics: {rows[0]['mode']}"
    fig, axes, key = figure_grid(1, 2, title)
    sns.scatterplot(
        data=frame,
        x="trial",
        y="p99_ms",
        hue="requested_mbps",
        palette="viridis",
        ax=axes[0],
        legend="full",
        s=75,
    )
    handles, labels = axes[0].get_legend_handles_labels()
    for handle, label in zip(handles, labels, strict=True):
        handle.set_label(f"{float(label):g} Mb/s requested background")
    axes[0].get_legend().remove()
    axes[0].set(xlabel="Trial", ylabel="Successful-call p99 (ms)")
    axes[0].xaxis.set_major_locator(MaxNLocator(nbins=8, integer=True))
    failures = frame[["trial", "timeout", "io_error", "skipped_capacity"]].melt(
        id_vars="trial", var_name="outcome", value_name="calls"
    )
    sns.barplot(
        data=failures,
        x="trial",
        y="calls",
        hue="outcome",
        ax=axes[1],
        errorbar=None,
    )
    outcome_handles, _ = axes[1].get_legend_handles_labels()
    for handle in outcome_handles:
        handle.set_label(handle.get_label().replace("_", " "))
    axes[1].get_legend().remove()
    axes[1].set(
        xlabel="Trial",
        ylabel="Calls or omitted slots",
        ylim=(0, max(1, failures["calls"].max() * 1.15)),
    )
    ticks = list(range(0, len(rows), max(1, len(rows) // 8)))
    axes[1].set_xticks(ticks, labels=[str(tick + 1) for tick in ticks])
    axes[1].yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
    if len(rows) <= 20:
        for container in axes[1].containers:
            axes[1].bar_label(container, padding=3, fontsize=8)
    footer(
        key,
        "Each point is one run. Call durations include retries and local processing.\n"
        "RPC is a separate best-effort phase; it does not measure the foreground classifier.\n"
        "All outcomes and background goodput are retained in rpc-summary.csv.",
        handles=[*handles, *outcome_handles],
    )
    layout = save_figure(
        fig, output / "rpc-diagnostics", transport="udp", transport_label="RPC transport"
    )
    totals = {
        name: int(frame[name].sum())
        for name in (
            "scheduled_calls",
            "admitted_calls",
            "completed",
            "timeout",
            "cancelled",
            "io_error",
            "skipped_capacity",
            "retransmissions",
        )
    }
    prose = (
        f"We scheduled {totals['scheduled_calls']:,} RPC calls across {len(rows)} runs. "
        f"Of these, {totals['completed']:,} completed, {totals['timeout']:,} timed out, "
        f"and {totals['skipped_capacity']:,} were omitted because all workers were busy.\n"
        f"The clients recorded {totals['retransmissions']:,} retransmissions. "
        "Successful-call percentiles exclude failed calls; "
        "the table keeps those failures visible.\n"
        "These runs check the RPC workload and its integration. They do not establish an "
        "exactly-once guarantee after a server restart or a benefit from queue classification.\n"
    )
    (output / "findings.txt").write_text(prose, encoding="utf-8")
    _manifest(output, inputs, totals, layout)
    return totals


def analyze_loopback(directories, output):
    if not 1 <= len(directories) <= 20:
        raise ValueError("loopback analysis needs between 1 and 20 runs")
    rows = [summarize(directory)[0] for directory in directories]
    if any(row["measurement_kind"] != "loopback_diagnostic" for row in rows):
        raise ValueError("loopback report accepts only real loopback diagnostics")
    output.mkdir(mode=0o755)
    _write_csv(output / "runs.csv", rows)
    frame = pd.DataFrame(rows).assign(trial=range(1, len(rows) + 1))
    fig, axes, key = figure_grid(1, 2, "Real loopback traffic: no shaped bottleneck")
    sns.scatterplot(
        data=frame,
        x="trial",
        y="p99_ms",
        hue="requested_mbps",
        ax=axes[0],
        legend="full",
        s=80,
        palette="viridis",
    )
    handles, labels = axes[0].get_legend_handles_labels()
    for handle, label in zip(handles, labels, strict=True):
        handle.set_label(f"{float(label):g} Mb/s requested background")
    axes[0].get_legend().remove()
    axes[0].set(xlabel="Trial", ylabel="On-time reply p99 RTT (ms)")
    axes[0].xaxis.set_major_locator(MaxNLocator(nbins=8, integer=True))
    sns.barplot(data=frame, x="trial", y="not_sent_rate", ax=axes[1], color="#BA0C2F")
    axes[1].set(xlabel="Trial", ylabel="Fraction of scheduled slots not sent")
    footer(
        key,
        f"{len(rows)} runs; colors identify requested TCP background traffic.\n"
        "All traffic stays on this host. There is no Linux queue-policy treatment or NIC path.\n"
        "Use these results to check collection and accounting, not hardware performance.",
        handles=handles,
    )
    layout = save_figure(fig, output / "loopback-diagnostics", transport=rows[0]["transport"])
    totals = {
        name: int(frame[name].sum())
        for name in (
            "scheduled",
            "sent",
            "on_time",
            "timeout_count",
            "not_sent",
        )
    }
    text = (
        f"We collected {totals['scheduled']:,} scheduled request slots on this host. "
        f"{totals['on_time']:,} replies arrived on time, {totals['timeout_count']:,} "
        f"missed the deadline, and {totals['not_sent']:,} slots were not sent.\n"
        "Loopback bypasses the NucBox, Ethernet adapters and shaped queue. It verifies "
        "that real sockets, retained records and the analysis work together. "
        "It cannot answer which queue policy performs best on the physical testbed.\n"
    )
    (output / "findings.txt").write_text(text, encoding="utf-8")
    _manifest(output, [{"manifest_sha256": row["manifest_sha256"]} for row in rows], totals, layout)
    return totals


def _manifest(output, inputs, totals, layout):
    atomic_json(
        output / "manifest.json",
        {
            "schema_version": 1,
            "eligible_for_primary": False,
            "inputs": inputs,
            "totals": totals,
            "layout": layout,
            "outputs": {path.name: digest(path) for path in sorted(output.iterdir())},
        },
    )
