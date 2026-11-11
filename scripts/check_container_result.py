"""Check the container rebuild against the published diagnostic point estimates."""

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.plot_artifacts import expected_artifacts  # noqa: E402
from src.artifacts import digest, read_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def check(directory: Path) -> None:
    reference = read_json(ROOT / "data/reference/namespace-pilot-2026-11-11/analysis/report.json")
    actual = read_json(directory / "report.json")
    if (
        actual["state"] != "completed"
        or type(actual["runs"]) is not int
        or actual["runs"] != 16
        or actual["eligible_for_primary"] is not False
    ):
        raise ValueError("container did not produce the expected diagnostic report")
    if len(actual["comparisons"]) != len(reference["comparisons"]):
        raise ValueError("container comparison count changed")
    for observed, expected in zip(actual["comparisons"], reference["comparisons"], strict=True):
        _compare_points(observed, expected)
    if not isinstance(actual["artifacts"], dict):
        raise ValueError("invalid container artifact map")
    expected_names = expected_artifacts(actual)
    for name, checksum in actual["artifacts"].items():
        if name not in expected_names or digest(directory / name) != checksum:
            raise ValueError("container output hash mismatch")
    if actual["artifacts"].keys() != expected_names:
        raise ValueError("container omitted an analysis artifact")


def _compare_points(observed, expected):
    if (
        observed["policy"] != expected["policy"]
        or type(observed["blocks"]) is not int
        or observed["blocks"] != 2
        or observed["interval_status"] != "insufficient_blocks"
    ):
        raise ValueError("container policy or pairing changed")
    for metric in ("added_p99_ms", "goodput_mbps", "goodput_retention_pct", "p99_reduction_pct"):
        if not math.isclose(observed[metric], expected[metric], rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError(f"container point estimate changed: {metric}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        check(args.directory)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Container result check failed: {error}", file=sys.stderr)
        return 2
    print("Container analysis matches the diagnostic point estimates and output hashes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
