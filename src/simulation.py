"""Seeded software-test data from an explicit toy model, never measured queue results."""

import csv
import hashlib
import math
import multiprocessing
import os
import platform
import random
import statistics
import time
from pathlib import Path
from threading import Event

from src.artifacts import atomic_json, digest, json_bytes, read_json
from src.experiment_config import ExperimentConfig, bounded_integer
from src.run_bundle import source_identity
from src.transport_summary import FIELDS as TRANSPORT_FIELDS

ROOT = Path(__file__).resolve().parents[1]
MODEL = {
    "version": "toy-queue-v1",
    "purpose": "software_testing_only",
    "delay_factors": {"fifo": 1.0, "fq_codel": 0.3, "cake_best_effort": 0.2, "cake_bounded": 0.16},
    "goodput_factors": {
        "fifo": 1.0,
        "fq_codel": 0.98,
        "cake_best_effort": 0.94,
        "cake_bounded": 0.95,
    },
}
REQUEST_FIELDS = ("run_id", "request_id", "elapsed_seconds", "outcome", "rtt_ms", "send_lag_ms")


def simulation_plan(multiplier: int = 3, seed: int = 561, *, transport="udp") -> dict:
    from src.transport import validate_transport

    validate_transport(transport)
    bounded_integer(multiplier, "simulation multiplier", 1, 10)
    bounded_integer(seed, "simulation seed", 0, 2**32 - 1)
    raw = read_json(ROOT / "configs/pilot.json", 65536)
    for key in ("repetitions", "unloaded_repetitions_per_policy"):
        raw[key] *= multiplier
    raw["random_seed"] = seed
    config = ExperimentConfig.from_mapping(raw)
    from src.campaign import resolve_trials

    schedule, _ = resolve_trials(raw, 10, diagnostic_matrix=True, transport=transport)
    return {
        "kind": "local_simulation",
        "transport": transport,
        "configuration": raw,
        "schedule": schedule,
        "source": source_identity(ROOT),
        "model": MODEL,
        "eligible_for_primary": False,
        "measurement_slots": config.total_runs * config.measurement_seconds * 500,
    }


def _quantile(values: list[float], fraction: float) -> float | None:
    return sorted(values)[math.ceil(fraction * len(values)) - 1] if values else None


def _parameters(cell, seed):
    block = random.Random(f"{seed}:{cell['block']}")
    rng = random.Random(f"{seed}:{cell['cell_id']}")
    baseline = 20 + block.uniform(-0.6, 0.6)
    load = cell["load_fraction"]
    delay = (12 * load**3 * MODEL["delay_factors"][cell["policy"]]) if cell["flows"] else 0
    goodput = (
        min(load * 100, 96) * MODEL["goodput_factors"][cell["policy"]] * rng.uniform(0.97, 1.02)
        if cell["flows"]
        else 0
    )
    return rng, baseline, delay, goodput


def simulate_trial(task: tuple) -> dict:
    directory, cell, seconds, seed, source, *selected = task
    transport = selected[0] if selected else "udp"
    started, cpu = time.monotonic(), time.process_time()
    directory = Path(directory)
    directory.mkdir(mode=0o700)
    token = hashlib.sha256(
        json_bytes({"cell": cell, "seed": seed, "model": MODEL, "transport": transport})
    ).hexdigest()
    rng, baseline, delay, goodput = _parameters(cell, seed)
    records = []
    for index in range(seconds * 500):
        missed = rng.random() < 0.004
        late = not missed and rng.random() < 0.0005
        rtt = (
            None
            if missed
            else round(max(0.001, baseline + delay + rng.expovariate(4)) + (1000 if late else 0), 6)
        )
        records.append(
            {
                "run_id": token[:32],
                "request_id": index,
                "elapsed_seconds": index / 500,
                "outcome": "not_sent" if missed else "late" if late else "on_time",
                "rtt_ms": rtt,
                "send_lag_ms": None if missed else round(rng.uniform(0.01, 0.2), 6),
            }
        )
    summary = _summary(records, cell, source, goodput)
    summary["transport"] = transport
    summary.update(dict.fromkeys(TRANSPORT_FIELDS))
    manifest = {
        "kind": "simulation",
        "cell": cell,
        "seed": seed,
        "model": MODEL,
        "summary": summary,
    }
    atomic_json(directory / "manifest.json", manifest)
    summary["manifest_sha256"] = digest(directory / "manifest.json")
    atomic_json(directory / "summary.json", summary)
    with (directory / "requests.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, REQUEST_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    return {
        "directory": directory.name,
        "cell_id": cell["cell_id"],
        "manifest_sha256": summary["manifest_sha256"],
        "state": "completed",
        "table_hashes": {
            "summary": digest(directory / "summary.json"),
            "requests": digest(directory / "requests.csv"),
        },
        "wall_seconds": time.monotonic() - started,
        "process_cpu_seconds": time.process_time() - cpu,
    }


def _summary(records, cell, source, goodput):
    good = [r["rtt_ms"] for r in records if r["outcome"] == "on_time"]
    lags = [r["send_lag_ms"] for r in records if r["send_lag_ms"] is not None]
    missed = sum(r["outcome"] == "not_sent" for r in records)
    late = sum(r["outcome"] == "late" for r in records)
    jitter = [
        abs(b["rtt_ms"] - a["rtt_ms"])
        for a, b in zip(records, records[1:], strict=False)
        if a["outcome"] == b["outcome"] == "on_time"
    ]
    return {
        "run_id": records[0]["run_id"],
        "policy": cell["policy"],
        "flows": cell["flows"],
        "requested_mbps": cell["load_fraction"] * 100,
        "measurement_kind": "simulation",
        "platform": platform.system(),
        "scheduled": len(records),
        "sent": len(records) - missed,
        "on_time": len(good),
        "timeout_count": late,
        "late_count": late,
        "not_sent": missed,
        "timeout_rate": late / (len(records) - missed),
        "not_sent_rate": missed / len(records),
        "p99_censored": late / (len(records) - missed) > 0.01,
        "jitter_ms": statistics.median(jitter) if jitter else None,
        "send_lag_p99_ms": _quantile(lags, 0.99),
        "goodput_mbps": goodput,
        "eligible_for_primary": False,
        "source_commit": source["commit"],
        "source_tree_sha256": source["tree_sha256"],
        "source_dirty": source["dirty"],
        **{
            name: _quantile(good, q)
            for name, q in zip(
                ("p50_ms", "p95_ms", "p99_ms", "p999_ms"), (0.5, 0.95, 0.99, 0.999), strict=True
            )
        },
    }


def collect_simulation(directory: Path, plan: dict, workers: int, cancel: Event) -> list[dict]:
    """At most eight spawned workers, one bounded run per task, and 160 planned tasks."""
    bounded_integer(workers, "workers", 1, 8)
    if cancel.is_set():
        raise InterruptedError("simulation cancelled before pool creation")
    directory.mkdir(mode=0o700)
    tasks = [
        (
            str(directory / f"trial-{index:03d}"),
            cell,
            plan["configuration"]["measurement_seconds"],
            plan["configuration"]["random_seed"],
            plan["source"],
            plan.get("transport", "udp"),
        )
        for index, cell in enumerate(plan["schedule"]["cells"], 1)
    ]
    deadline = time.monotonic() + 120
    with multiprocessing.get_context("spawn").Pool(workers, maxtasksperchild=32) as pool:
        pending = pool.map_async(simulate_trial, tasks, chunksize=1)
        while not pending.ready():
            if cancel.wait(0.05):
                raise InterruptedError("simulation cancelled; partial trials retained")
            if time.monotonic() >= deadline:
                raise TimeoutError("simulation exceeded its 120-second deadline")
        return pending.get()


def default_workers() -> int:
    return min(4, os.cpu_count() or 1)
