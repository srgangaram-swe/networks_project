"""Plot every run-level observation in a checked loopback diagnostic export."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.artifacts import digest, read_json  # noqa: E402


def plot(directory: Path, output: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    import seaborn as sns

    provenance = read_json(directory / "provenance.json", 65536)
    if digest(directory / "summary.csv") != provenance["summary_sha256"]:
        raise ValueError("summary digest differs from export provenance")
    data = pd.read_csv(directory / "summary.csv")
    if (
        data.empty
        or len(data) != provenance["run_count"]
        or not data["measurement_kind"].eq("loopback_diagnostic").all()
    ):
        raise ValueError("this figure requires loopback diagnostics, with every run included")
    if output.exists():
        raise FileExistsError("choose a new figure path")
    data["TCP streams"] = data["flows"].astype(str)
    data["not_sent_percent"] = data["not_sent_rate"] * 100
    sns.set_theme(style="whitegrid", context="notebook", font_scale=1.05)
    figure, axes = plt.subplots(2, 2, figsize=(11, 8), layout="constrained")
    panels = (
        ("p99_ms", "On-time foreground p99 (ms)"),
        ("send_lag_p99_ms", "Sender delay p99 (ms)"),
        ("not_sent_percent", "Scheduled requests not sent (%)"),
        ("goodput_mbps", "Receiver TCP goodput (Mb/s)"),
    )
    for axis, (metric, label) in zip(axes.flat, panels, strict=True):
        sns.swarmplot(
            data=data,
            x="TCP streams",
            y=metric,
            hue="TCP streams",
            palette="colorblind",
            size=9,
            alpha=0.75,
            legend=False,
            ax=axis,
        )
        axis.set_ylabel(label)
        ceiling = max(float(data[metric].max()), 0.001)
        axis.set_ylim(-0.035 * ceiling, 1.12 * ceiling)
        axis.grid(axis="x", visible=False)
        sns.despine(ax=axis)
    for target in sorted(data["requested_mbps"].unique()):
        axes[1, 1].axhline(
            target, color="0.3", linestyle=":", linewidth=1.4, label=f"Requested {target:g} Mb/s"
        )
    axes[1, 1].legend(loc="best", frameon=False)
    timeouts = int(data["timeout_count"].sum())
    figure.suptitle(
        "Loopback development diagnostics\nNo shaped bottleneck or Linux queue comparison",
        fontsize=17,
    )
    figure.supxlabel(
        f"Each dot is one run. {len(data)} runs, "
        f"{int(data['scheduled'].sum()):,} scheduled, {int(data['not_sent'].sum())} not sent, "
        f"{timeouts} reply deadline misses.\n"
        "Receiver and foreground windows are not aligned; primary collection remains blocked.",
        fontsize=10,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180, metadata={"Creator": "Network experiment plotting script"})
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        plot(args.directory, args.output)
    except (OSError, ValueError, ImportError) as exc:
        print(f"Plot failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
