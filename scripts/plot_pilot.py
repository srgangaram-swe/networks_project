"""Plot every completed namespace pilot run from a checked diagnostic export."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.artifacts import digest, read_json  # noqa: E402


def plot(source: Path, destination: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    import seaborn as sns

    if destination.exists():
        raise FileExistsError("choose a new figure path")
    provenance = read_json(source / "provenance.json", 65536)
    for name in ("summary", "requests"):
        if digest(source / f"{name}.csv") != provenance[f"{name}_sha256"]:
            raise ValueError(f"{name} export digest changed")
    summary = pd.read_csv(source / "summary.csv")
    requests = pd.read_csv(source / "requests.csv")
    if set(summary["measurement_kind"]) != {"virtual_testbed"}:
        raise ValueError("this figure requires observed namespace trials")
    if len(summary) != provenance["run_count"] or len(requests) != provenance["request_count"]:
        raise ValueError("export counts do not reconcile")
    attempts = read_json(source / "attempts.json")
    failed = sum(row["status"] != "completed" for row in attempts["attempts"])
    unattempted = len(attempts["plan"]["schedule"]["cells"]) - len(
        {row["cell_id"] for row in attempts["attempts"]}
    )
    names = {
        "fifo": "FIFO",
        "fq_codel": "FQ-CoDel",
        "cake_best_effort": "CAKE BE",
        "cake_bounded": "CAKE bounded",
    }
    summary["Policy"] = summary["policy"].map(names)
    summary["Condition"] = summary["flows"].map({0: "Unloaded", 1: "110 Mb/s requested"})
    summary["Unsent slots (%)"] = 100 * summary["not_sent_rate"]
    order = list(names.values())
    sns.set_theme(style="whitegrid", context="notebook", font_scale=1.05)
    fig, axes = plt.subplots(2, 2, figsize=(14, 10), constrained_layout=False)
    sns.swarmplot(
        data=summary,
        x="Policy",
        y="p99_ms",
        hue="Condition",
        dodge=True,
        order=order,
        palette="colorblind",
        size=7,
        ax=axes[0, 0],
    )
    axes[0, 0].set(
        title="Foreground p99 by run", xlabel="", ylabel="On-time RTT (ms)", ylim=(0, None)
    )
    axes[0, 0].legend(title=None, fontsize=9)
    loaded = summary[summary["flows"] > 0]
    sns.swarmplot(
        data=loaded,
        x="Policy",
        y="goodput_mbps",
        order=order,
        color="#0072B2",
        size=7,
        ax=axes[0, 1],
    )
    axes[0, 1].axhline(100, color="0.5", linestyle=":", linewidth=1)
    axes[0, 1].set(
        title="Bulk TCP receiver goodput by run", xlabel="", ylabel="Mb/s", ylim=(0, 110)
    )
    sns.swarmplot(
        data=summary,
        x="Policy",
        y="Unsent slots (%)",
        hue="Condition",
        dodge=True,
        order=order,
        palette="colorblind",
        size=7,
        ax=axes[1, 0],
    )
    axes[1, 0].set(title="Generator omissions remain visible", xlabel="", ylim=(0, None))
    axes[1, 0].legend_.remove()
    distributions = requests.merge(
        loaded[["run_id", "Policy"]], on="run_id", validate="many_to_one"
    )
    observed = distributions[distributions["outcome"] == "on_time"]
    sns.ecdfplot(
        data=observed,
        x="rtt_ms",
        hue="Policy",
        hue_order=order,
        palette="colorblind",
        ax=axes[1, 1],
    )
    axes[1, 1].set(
        title="Loaded RTT distribution, descriptive pooled requests",
        xlabel="On-time RTT (ms, logarithmic axis)",
        ylabel="Fraction",
        xscale="log",
    )
    fig.suptitle(
        "Virtual testbed pilot: queue behavior and measurement limits", fontsize=18, y=0.98
    )
    caption = (
        f"{len(summary)} completed runs; {failed} failed attempts; "
        f"{unattempted} unattempted cells. "
        f"{int(summary['scheduled'].sum()):,} measured slots; "
        f"{int(summary['not_sent'].sum()):,} unsent; "
        f"{int(summary['timeout_count'].sum()):,} timeouts.\n"
        "Every completed run is shown. Two blocks are a mechanics check, "
        "not a precise effect estimate.\n"
        "Primary collection: NO-GO. TCP and foreground windows differ; "
        "CPU accounting covers the shared host."
    )
    fig.text(0.05, 0.025, caption, fontsize=10, va="bottom")
    fig.subplots_adjust(left=0.075, right=0.97, top=0.91, bottom=0.17, wspace=0.26, hspace=0.35)
    with destination.open("xb") as stream:
        fig.savefig(stream, format="png", dpi=180)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plot(args.source, args.output)
    except (OSError, ValueError, KeyError) as exc:
        print(f"Pilot plot failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
