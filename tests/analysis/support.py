"""Hand-computable exports created only in temporary test directories."""

import csv
import hashlib
from pathlib import Path

import pandas as pd

from src.artifacts import atomic_json, digest, read_json
from src.experiment_config import ExperimentConfig
from src.schedule import make_schedule

ROOT = Path(__file__).resolve().parents[2]


def fixture(directory, blocks=3, policies=("fifo", "fq_codel")):
    config = read_json(ROOT / "configs/pilot.json")
    config.update(
        policies=list(policies),
        repetitions=blocks,
        unloaded_repetitions_per_policy=blocks,
        measurement_seconds=1,
    )
    schedule = make_schedule(ExperimentConfig.from_mapping(config))
    source = {"commit": "1" * 40, "tree_sha256": "2" * 64, "dirty": False}
    plan = {"configuration": config, "schedule": schedule, "source": source}
    summaries, requests, attempts = [], [], []
    for cell in schedule["cells"]:
        token = hashlib.sha256(cell["cell_id"].encode()).hexdigest()
        run_id = token[:32]
        factor = {"fifo": 1, "fq_codel": 0.4, "cake_best_effort": 0.6, "cake_bounded": 0.2}[
            cell["policy"]
        ]
        latency = 20 + cell["block"] + (10 + cell["block"]) * factor * bool(cell["flows"])
        goodput = (
            (100 + cell["block"]) * (1 if cell["policy"] == "fifo" else 0.95) * bool(cell["flows"])
        )
        summaries.append(
            {
                "run_id": run_id,
                "policy": cell["policy"],
                "measurement_kind": "virtual_testbed",
                "platform": "Linux",
                "flows": cell["flows"],
                "requested_mbps": cell["load_fraction"] * 100,
                "p50_ms": latency,
                "p95_ms": latency,
                "p99_ms": latency,
                "p999_ms": latency,
                "jitter_ms": 0,
                "send_lag_p99_ms": 0.001,
                "goodput_mbps": goodput,
                "timeout_rate": 0,
                "not_sent_rate": 0,
                "scheduled": 500,
                "sent": 500,
                "on_time": 500,
                "timeout_count": 0,
                "late_count": 0,
                "not_sent": 0,
                "p99_censored": False,
                "eligible_for_primary": False,
                "source_commit": source["commit"],
                "source_tree_sha256": source["tree_sha256"],
                "source_dirty": False,
                "manifest_sha256": token,
            }
        )
        requests.extend(
            {
                "run_id": run_id,
                "request_id": i,
                "elapsed_seconds": i / 500,
                "outcome": "on_time",
                "rtt_ms": latency,
                "send_lag_ms": 0.001,
            }
            for i in range(500)
        )
        attempts.append(
            {"cell_id": cell["cell_id"], "status": "completed", "manifest_sha256": token}
        )
    return write_export(
        directory,
        pd.DataFrame(summaries),
        pd.DataFrame(requests),
        {"plan": plan, "attempts": attempts},
    )


def write_export(directory, summaries, requests, design):
    directory.mkdir(exist_ok=True)
    summaries.to_csv(directory / "summary.csv", index=False)
    requests.to_csv(directory / "requests.csv", index=False)
    atomic_json(directory / "attempts.json", design)
    refresh(directory)
    return directory


def refresh(directory):
    counts = []
    for name in ("summary", "requests"):
        with (directory / f"{name}.csv").open() as stream:
            counts.append(sum(1 for _ in csv.DictReader(stream)))
    atomic_json(
        directory / "provenance.json",
        {
            "schema_version": 1,
            "eligible_for_primary": False,
            "run_count": counts[0],
            "request_count": counts[1],
            "summary_sha256": digest(directory / "summary.csv"),
            "requests_sha256": digest(directory / "requests.csv"),
            "attempts_sha256": digest(directory / "attempts.json"),
        },
    )
