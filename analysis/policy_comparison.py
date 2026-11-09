from pathlib import Path
import json
import hashlib
import argparse
import sys
import pandas as pd
import numpy as np

from analysis.utils.load_data import load_data
from analysis.utils.summarize_runs import summarize_runs
from analysis.utils.match_baselines import match_baselines
from analysis.utils.compare_policies import compare_policies



def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze network experiment results."
    )

    parser.add_argument(
        "directory",
        type=Path,
        help="Directory containing summary.csv, requests.csv, and provenance.json",
    )

    parser.add_argument(
        "--output",
        type=Path,
        help="Optional directory for saving analysis results.",
    )

    args = parser.parse_args()

    try:
        # 1. Load and validate experimental data.
        summaries, requests, provenance = load_data(args.directory)

        print(f"Loaded {len(summaries)} experimental runs.")
        print(f"Loaded {len(requests)} foreground requests.")

        if not provenance.get("eligible_for_primary", False):
            print(
                "WARNING: This dataset is not eligible "
                "for primary experimental comparisons."
            )

        # 2. Calculate descriptive statistics.
        run_statistics = summarize_runs(summaries)

        print("\n=== Run Statistics ===")
        print(run_statistics)

        # 3. Calculate baseline-adjusted latency.
        baseline_results = match_baselines(summaries)

        print("\n=== Baseline Comparisons ===")
        print(baseline_results)

        # 4. Compare policies against FIFO.
        policy_results = compare_policies(
            summaries,
            fifo_policy="fifo",
            confidence=0.95,
            n_resamples=10000,
            random_state=42,
        )

        print("\n=== Policy Comparisons ===")
        print(policy_results)

        # 5. Save results if an output directory was provided.
        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)

            run_statistics.to_csv(
                args.output / "run_statistics.csv"
            )

            baseline_results.to_csv(
                args.output / "baseline_results.csv",
                index=False,
            )

            policy_results.to_csv(
                args.output / "policy_comparisons.csv",
                index=False,
            )

            print(f"\nResults saved to {args.output}")

    except (FileNotFoundError, ValueError, KeyError, pd.errors.EmptyDataError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())