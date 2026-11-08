"""Verify the recorded candidate against executable namespace command plans."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.testbed_contract import CONTRACT_PATH, verify_contract  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    try:
        print(json.dumps(verify_contract(parser.parse_args().contract), sort_keys=True))
    except (OSError, ValueError) as exc:
        print(f"Contract verification failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
