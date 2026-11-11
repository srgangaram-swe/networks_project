"""Validate exports, compare paired policies, and describe exploratory run clusters."""

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path

import pandas as pd

from analysis.plots import clustering_plot, comparison_plot
from analysis.run_clustering import cluster_runs
from analysis.utils.compare_policies import compare_policies
from analysis.utils.load_data import load_data
from analysis.utils.match_baselines import match_baselines
from analysis.utils.summarize_runs import summarize_runs
from src.artifacts import atomic_json, digest
from src.run_bundle import source_identity

ROOT = Path(__file__).resolve().parents[1]


def analyze(
    directories: list[Path], output: Path, resamples: int = 10000, plots: bool = True
) -> dict:
    if output.exists() or output.is_symlink():
        raise FileExistsError("choose an unused analysis output directory")
    if not 1 <= len(directories) <= 20:
        raise ValueError("analyze between one and twenty bounded exports")
    frames, inputs = [], []
    for directory in directories:
        summaries, _, provenance = load_data(directory)
        frames.append(summaries)
        inputs.append(provenance)
    summaries = pd.concat(frames, ignore_index=True)
    if summaries["run_id"].duplicated().any():
        raise ValueError("duplicate run across input exports")
    if (
        len(
            summaries[["source_commit", "source_tree_sha256", "measurement_kind"]].drop_duplicates()
        )
        != 1
    ):
        raise ValueError("analyze different source versions or testbed kinds separately")
    matched = match_baselines(summaries)
    if summaries["cohort"].nunique() != 1:
        raise ValueError("analyze different campaign designs separately")
    comparisons = compare_policies(summaries, n_resamples=resamples)
    assignments, model = cluster_runs(summaries)
    report = {
        "schema_version": 1,
        "state": "writing",
        "eligible_for_primary": False,
        "runs": len(summaries),
        "analysis_source": {
            **source_identity(ROOT),
            "module_sha256": {
                str(p.relative_to(ROOT)): digest(p)
                for p in sorted((ROOT / "analysis").rglob("*.py"))
            },
        },
        "unobserved_planned_cells": max(
            item.get("planned_cells", len(summaries)) for item in inputs
        )
        - len(summaries),
        "inputs": inputs,
        "bootstrap_unit": "paired_block",
        "bootstrap_seed": 562,
        "resamples": resamples,
        "confidence": 0.95,
        "minimum_blocks_for_interval": 3,
        "ml": model,
        "comparisons": json.loads(comparisons.to_json(orient="records")),
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "scikit-learn", "scipy")
        },
    }
    _write_results(output, summaries, matched, comparisons, assignments, report, plots)
    return report


def _write_results(output, summaries, matched, comparisons, assignments, report, plots):
    output.mkdir(mode=0o700)
    atomic_json(output / "report.json", report)
    try:
        for name, frame in (
            ("runs", summaries),
            ("matched_baselines", matched),
            ("policy_comparisons", comparisons),
            ("run_clusters", assignments),
        ):
            frame.to_csv(output / f"{name}.csv", index=False, mode="x")
        summarize_runs(summaries).to_csv(output / "run_statistics.csv", mode="x")
        if plots:
            comparison_plot(matched, comparisons, output / "policy_comparisons.png")
            clustering_plot(assignments, output / "run_clusters.png")
            clustering_plot(assignments, output / "run_clusters_tsne.png", projection="tsne")
        report["artifacts"] = {
            p.name: digest(p) for p in sorted(output.iterdir()) if p.name != "report.json"
        }
        report["state"] = "completed"
        atomic_json(output / "report.json", report)
    except (OSError, ValueError, RuntimeError) as error:
        report["state"] = "failed"
        report["error_type"] = type(error).__name__
        try:
            atomic_json(output / "report.json", report)
        except (OSError, ValueError) as persistence:
            error.add_note(f"analysis report could not be retained: {persistence}")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resamples", type=int, default=10000)
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    try:
        report = analyze(args.directory, args.output, args.resamples, not args.no_plots)
        print(
            json.dumps(
                {"state": report["state"], "runs": report["runs"], "eligible_for_primary": False}
            )
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, UnicodeError) as error:
        print(f"Analysis failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
