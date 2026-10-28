"""Save the randomized, paired experiment schedule without running traffic."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.artifacts import json_bytes, read_json  # noqa: E402
from src.experiment_config import ExperimentConfig  # noqa: E402
from src.schedule import make_schedule  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = make_schedule(ExperimentConfig.from_mapping(read_json(args.config, 65536)))
        with args.output.open("xb") as stream:
            stream.write(json_bytes(result))
    except (OSError, ValueError) as exc:
        print(f"Schedule failed: {exc}", file=sys.stderr)
        return 2
    print(f"Saved {len(result['cells'])} cells; no traffic was generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
