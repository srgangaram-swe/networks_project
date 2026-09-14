"""Check a JSON configuration and print planning counts, never measurements."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.experiment_config import ExperimentConfig  # noqa: E402

MAX_CONFIG_BYTES = 65536


def distinct_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate configuration key: {key}")
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    try:
        with args.config.open("rb") as source:
            payload = source.read(MAX_CONFIG_BYTES + 1)
        if len(payload) > MAX_CONFIG_BYTES:
            raise ValueError("configuration exceeds the 65536-byte limit")
        raw = json.loads(payload, object_pairs_hook=distinct_keys)
        config = ExperimentConfig.from_mapping(raw)
    except (OSError, ValueError, RecursionError) as error:
        print(f"Invalid configuration: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "valid_plan",
                "loaded_runs": config.loaded_runs,
                "unloaded_runs": config.unloaded_runs,
                "total_runs": config.total_runs,
                "measurement_seconds_total": config.measurement_seconds_total,
                "network_changes": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
