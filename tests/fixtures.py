"""Small deterministic examples for corruption and arithmetic tests."""

from dataclasses import asdict
from pathlib import Path

from src.foreground import Workload
from src.run_bundle import TRANSITIONS, RunBundle
from src.trial import TrialConfig


def capture(plan: Workload | None = None) -> dict:
    plan = plan or Workload(0, 1000, 2000, 500)
    start = 1_000_000_000
    measurement_start = start + plan.warmup_ms * 1_000_000
    measurement_end = measurement_start + plan.measurement_ms * 1_000_000
    rows = []
    for index in range(plan.total_count):
        due = start + index * 1_000_000_000 // plan.requests_per_second
        rows.append(
            {
                "schema_version": 1,
                "request_id": index,
                "scheduled_ns": due,
                "sent_ns": due + 1000,
                "received_ns": due + 1_001_000,
            }
        )
    return {
        "schema_version": 1,
        "protocol_status": "proposed",
        "status": "completed",
        "config": asdict(plan),
        "start_ns": start,
        "measurement_start_ns": measurement_start,
        "measurement_end_ns": measurement_end,
        "planned_end_ns": measurement_end + plan.drain_ms * 1_000_000,
        "finished_ns": measurement_end + plan.drain_ms * 1_000_000 + 1000,
        "incomplete_deadlines": 0,
        "counts": {
            "warmup": {"on_time": plan.warmup_count, "late": 0, "timeout": 0, "not_sent": 0},
            "measurement": {
                "on_time": plan.total_count - plan.warmup_count,
                "late": 0,
                "timeout": 0,
                "not_sent": 0,
            },
        },
        "event_counts": {},
        "events_dropped": 0,
        "events": [],
        "records": rows,
        "client_process_cpu_ns": 1_000_000,
        "socket_error_errno": None,
        "bind": ["127.0.0.1", 42001],
        "peer": ["127.0.0.1", 42000],
        "clock_resolution_seconds": 1e-9,
    }


def valid_bundle(directory: Path) -> RunBundle:
    config = TrialConfig(measurement_seconds=1)
    bundle = RunBundle(
        directory, asdict(config), {"commit": "a" * 40, "tree_sha256": "b" * 64, "dirty": False}
    )
    foreground = capture()
    bundle.artifact("foreground.json", foreground)
    bulk = {
        "requested": asdict(config.bulk_plan()),
        "per_flow_bps": 8_000_000,
        "actual_flows": 1,
        "receiver_bytes": 1_000_000,
        "receiver_seconds": 1.0,
        "goodput_mbps": 8.0,
        "intervals": [{"start_seconds": 0, "end_seconds": 1, "bytes": 1_000_000}],
        "tool_version": "synthetic fixture",
        "exit_status": 0,
        "window": "iperf_receiver",
        "foreground_window_aligned": False,
    }
    bundle.artifact("bulk.json", bulk)
    bundle.artifact(
        "cpu.json", {"scope": "unavailable", "busy_percent": None, "iowait_percent": None}
    )
    for name in ("queues-before.json", "queues-after.json"):
        bundle.artifact(
            name, {"kind": "loopback", "network_changes": False, "queue_verified": False}
        )
    bundle.manifest["phases"] = {
        key: foreground[key] for key in ("start_ns", "measurement_start_ns", "measurement_end_ns")
    }
    bundle.manifest["phases"]["end_ns"] = foreground["planned_end_ns"]
    state = "created"
    while state != "completed":
        state = next(iter(TRANSITIONS[state]))
        bundle.transition(state)
    return bundle
