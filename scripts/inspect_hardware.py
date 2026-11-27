"""Print local NIC and tool evidence without changing the machine."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.hardware_probe import local_hardware  # noqa: E402


def main() -> int:
    try:
        report = local_hardware()
        print(json.dumps(report, indent=2, sort_keys=True))
    except (OSError, ValueError) as exc:
        print(f"Hardware inspection failed: {exc}", file=sys.stderr)
        return 2
    return 0 if report["status"] == "inspection_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
