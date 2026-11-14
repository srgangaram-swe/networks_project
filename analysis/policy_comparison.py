"""Validate exports, compare paired policies, and describe exploratory run clusters."""

import argparse
import importlib.metadata
import json
import platform
import sys
from pathlib import Path

import pandas as pd

from analysis.findings import write_findings
from analysis.plots import render_plots
from analysis.regression import regress_runs
from analysis.run_clustering import cluster_runs
from analysis.utils.compare_policies import compare_policies
from analysis.utils.load_data import load_data
from analysis.utils.match_baselines import match_baselines
from analysis.utils.summarize_runs import summarize_runs
from analysis.writeup import write_summary
from src.artifacts import atomic_json, digest
from src.export_batches import MAX_ANALYSIS_RUNS, export_inputs
from src.run_bundle import source_identity
from src.telemetry import Telemetry

ROOT = Path(__file__).resolve().parents[1]


def analyze(
    directories: list[Path],
    output: Path,
    resamples: int = 10000,
    plots: bool = True,
    *,
    allow_simulated: bool = False,
) -> dict:
    if output.exists() or output.is_symlink():
        raise FileExistsError("choose an unused analysis output directory")
    timing = Telemetry(None)
    with timing.stage("load_and_validate"):
        summaries, inputs = _load_inputs(directories, allow_simulated)
    with timing.stage("baseline_pairing"):
        matched = match_baselines(summaries)
    with timing.stage("policy_comparisons"):
        comparisons = compare_policies(summaries, n_resamples=resamples)
    with timing.stage("clustering"):
        assignments, model = cluster_runs(summaries)
    with timing.stage("regression"):
        predictions, regression = regress_runs(matched)
    report = _report(summaries, inputs, comparisons, model, regression, resamples, plots)
    report["stage_timings"] = timing.stages
    _write_results(
        output, summaries, matched, comparisons, assignments, predictions, report, plots, timing
    )
    return report


def _load_inputs(directories, allow_simulated):
    frames, inputs = [], []
    run_count = 0
    for directory, binding in export_inputs(directories):
        summaries, _, provenance = load_data(
            directory, binding=binding, allow_simulated=allow_simulated
        )
        run_count += len(summaries)
        if run_count > MAX_ANALYSIS_RUNS:
            raise ValueError("analysis exceeds 400 run rows")
        frames.append(summaries)
        inputs.append(provenance)
    summaries = pd.concat(frames, ignore_index=True)
    if summaries["run_id"].duplicated().any():
        raise ValueError("duplicate run across input exports")
    if (
        len(
            summaries[
                ["source_commit", "source_tree_sha256", "measurement_kind", "transport"]
            ].drop_duplicates()
        )
        != 1
    ):
        raise ValueError("analyze different source versions or testbed kinds separately")
    if summaries["cohort"].nunique() != 1:
        raise ValueError("analyze different campaign designs separately")
    return summaries, inputs


def _report(summaries, inputs, comparisons, model, regression, resamples, plots):
    return {
        "schema_version": 1,
        "state": "writing",
        "eligible_for_primary": False,
        "runs": len(summaries),
        "measurement_kind": summaries["measurement_kind"].iloc[0],
        "transport": summaries["transport"].iloc[0],
        "plot_bundle_version": 3,
        "plots_requested": plots,
        "runtime": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
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
        "ml": {
            **model,
            "measurement_kind": summaries["measurement_kind"].iloc[0],
            "transport": summaries["transport"].iloc[0],
        },
        "regression": regression,
        "comparisons": json.loads(comparisons.to_json(orient="records", double_precision=15)),
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "scikit-learn", "scipy", "matplotlib", "seaborn")
        },
    }


def _write_results(
    output, summaries, matched, comparisons, assignments, predictions, report, plots, timing
):
    output.mkdir(mode=0o700)
    atomic_json(output / "report.json", report)
    try:
        for name, frame in (
            ("runs", summaries),
            ("matched_baselines", matched),
            ("policy_comparisons", comparisons),
            ("run_clusters", assignments),
            ("regression_predictions", predictions),
        ):
            frame.to_csv(output / f"{name}.csv", index=False, mode="x")
        summarize_runs(summaries).to_csv(output / "run_statistics.csv", mode="x")
        write_summary(output, summaries, report)
        write_findings(output, summaries, report)
        metrics = [
            {
                "requested_mbps": group["requested_mbps"],
                "flows": group["flows"],
                "algorithm": method,
                **values,
            }
            for group in report["ml"]["groups"]
            if group["status"] == "exploratory_fit"
            for method, values in group["diagnostics"]["partitions"].items()
        ]
        pd.DataFrame(
            metrics,
            columns=[
                "requested_mbps",
                "flows",
                "algorithm",
                "clusters",
                "noise_runs",
                "noise_fraction",
                "silhouette",
                "davies_bouldin",
                "calinski_harabasz",
                "score_scope",
                "adjusted_rand_agreement_with_kmeans",
            ],
        ).to_csv(output / "cluster_diagnostics.csv", index=False, mode="x")
        if plots:
            for frame in (summaries, matched, assignments, predictions):
                frame.attrs["measurement_kind"] = report["measurement_kind"]
                frame.attrs["transport"] = report["transport"]
            with timing.stage("plotting"):
                report["plot_layout"] = render_plots(
                    summaries,
                    matched,
                    comparisons,
                    assignments,
                    report["ml"],
                    output / "plots",
                    predictions=predictions,
                    regression=report["regression"],
                    timings=timing.stages,
                )
        atomic_json(
            output / "analysis_timings.json", {"stages": timing.stages, "clock": "monotonic"}
        )
        report["artifacts"] = {
            str(p.relative_to(output)): digest(p)
            for p in sorted(output.rglob("*"))
            if p.is_file() and p.name != "report.json"
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
    parser.add_argument("--allow-simulated", action="store_true")
    args = parser.parse_args()
    try:
        report = analyze(
            args.directory,
            args.output,
            args.resamples,
            not args.no_plots,
            allow_simulated=args.allow_simulated,
        )
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
