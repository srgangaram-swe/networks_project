"""Enforce the core branch floor separately from combined statement coverage."""

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    totals = json.loads(args.report.read_text())["totals"]
    covered, total = totals["covered_branches"], totals["num_branches"]
    percent = 100 * covered / total if total else 100
    print(f"Core branch coverage: {covered}/{total} ({percent:.2f}%; required 90%).")
    return 0 if covered * 100 >= total * 90 else 1


if __name__ == "__main__":
    raise SystemExit(main())
