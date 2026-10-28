"""Check complete run evidence independently of the trial runner."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bundle_validation import validate_bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(validate_bundle(args.directory), sort_keys=True))
    except (OSError, ValueError) as exc:
        print(f"Invalid bundle: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
