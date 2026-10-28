"""Print a read-only tool inventory; this does not authorize testbed use."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.testbed_inventory import local_inventory  # noqa: E402


def main() -> int:
    report = local_inventory()
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "inspection_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
