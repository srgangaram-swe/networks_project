"""Independent, fail-closed validation of manifests and foreground captures."""

import re
from collections import Counter
from dataclasses import fields
from datetime import datetime
from pathlib import Path

from src.artifacts import digest, read_json
from src.experiment_config import POLICIES, bounded_integer, bounded_number
from src.foreground import MAX_EVENTS, Workload
from src.foreground_io import endpoint
from src.measurement_contract import MAX_TIMESTAMP_NS, RequestRecord
from src.queue_policy import check_queue_kinds
from src.run_bundle import TRANSITIONS
from src.topology import Topology, inspection_commands

MANIFEST_FIELDS = {
    "schema_version",
    "run_id",
    "state",
    "started_utc",
    "source",
    "mode",
    "policy",
    "units",
    "artifacts",
    "history",
    "errors",
    "phases",
    "validity",
}
ARTIFACTS = {
    "configuration.json",
    "environment.json",
    "foreground.json",
    "bulk.json",
    "cpu.json",
    "queues-before.json",
    "queues-after.json",
}
CAPTURE_FIELDS = {
    "schema_version",
    "protocol_status",
    "status",
    "config",
    "start_ns",
    "measurement_start_ns",
    "measurement_end_ns",
    "planned_end_ns",
    "finished_ns",
    "incomplete_deadlines",
    "counts",
    "event_counts",
    "events_dropped",
    "events",
    "records",
    "client_process_cpu_ns",
    "socket_error_errno",
    "bind",
    "peer",
    "clock_resolution_seconds",
}
EVENT_KINDS = {
    "wrong_peer",
    "socket_error",
    "generator_late",
    "in_flight_limit",
    "send_would_block",
    "send_error",
    "payload_mismatch",
    "malformed_reply",
    "unknown_request",
    "request_mismatch",
    "clock_order_error",
    "duplicate_reply",
    "not_attempted",
}
NOT_SENT_EVENTS = {
    "generator_late",
    "in_flight_limit",
    "send_would_block",
    "send_error",
    "not_attempted",
}
OUTCOMES = ("on_time", "late", "timeout", "not_sent")


def exact_fields(value: object, expected: set, name: str) -> dict:
    if not isinstance(value, dict) or value.keys() != expected:
        raise ValueError(f"{name} must contain exactly the documented fields")
    return value


def _capture_times(raw: dict, plan: Workload) -> None:
    start = bounded_integer(raw["start_ns"], "start_ns", 0, MAX_TIMESTAMP_NS)
    expected = {
        "measurement_start_ns": start + plan.warmup_ms * 1_000_000,
        "measurement_end_ns": start + (plan.warmup_ms + plan.measurement_ms) * 1_000_000,
        "planned_end_ns": start
        + (plan.warmup_ms + plan.measurement_ms + plan.drain_ms) * 1_000_000,
    }
    for key, value in expected.items():
        bounded_integer(raw[key], key, value, value)
    bounded_integer(raw["finished_ns"], "finished_ns", raw["planned_end_ns"], MAX_TIMESTAMP_NS)
    bounded_integer(raw["incomplete_deadlines"], "incomplete_deadlines", 0, 0)
    bounded_integer(raw["client_process_cpu_ns"], "client_process_cpu_ns", 0, MAX_TIMESTAMP_NS)
    bounded_number(raw["clock_resolution_seconds"], "clock resolution", 1e-12, 1)


def _capture_records(raw: dict, plan: Workload) -> list[RequestRecord]:
    rows = raw["records"]
    if not isinstance(rows, list) or len(rows) != plan.total_count:
        raise ValueError("capture does not retain every scheduled request")
    records = []
    for index, row in enumerate(rows):
        record = RequestRecord.from_mapping(row)
        scheduled = raw["start_ns"] + index * 1_000_000_000 // plan.requests_per_second
        if record.request_id != index or record.scheduled_ns != scheduled:
            raise ValueError("request IDs or scheduled timestamps do not match the plan")
        for timestamp in (record.sent_ns, record.received_ns):
            if timestamp is not None and timestamp > raw["finished_ns"]:
                raise ValueError("request timestamp is later than capture completion")
        records.append(record)
    expected = {}
    for name, phase in (
        ("warmup", records[: plan.warmup_count]),
        ("measurement", records[plan.warmup_count :]),
    ):
        counts = Counter(record.outcome for record in phase)
        expected[name] = {key: counts[key] for key in OUTCOMES}
    if raw["counts"] != expected:
        raise ValueError("reported outcome counts do not reconcile with request records")
    for phase in raw["counts"].values():
        for value in phase.values():
            bounded_integer(value, "outcome count", 0, plan.total_count)
    return records


def _capture_events(raw: dict, records: list[RequestRecord]) -> None:
    bounded_integer(raw["events_dropped"], "events_dropped", 0, 0)
    events = raw["events"]
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError("invalid event log")
    counts: Counter = Counter()
    unsent = set()
    for event in events:
        exact_fields(event, {"kind", "observed_ns", "request_id"}, "event")
        if not isinstance(event["kind"], str) or event["kind"] not in EVENT_KINDS:
            raise ValueError("unsupported event kind")
        bounded_integer(
            event["observed_ns"], "event timestamp", raw["start_ns"], raw["finished_ns"]
        )
        request_id = event["request_id"]
        if request_id is not None:
            bounded_integer(request_id, "event request_id", 0, 2**64 - 1)
        if event["kind"] in NOT_SENT_EVENTS:
            unsent.add(request_id)
        counts[event["kind"]] += 1
    if dict(counts) != raw["event_counts"]:
        raise ValueError("event counts do not reconcile with the detailed log")
    for value in raw["event_counts"].values():
        bounded_integer(value, "event count", 1, MAX_EVENTS)
    if unsent != {record.request_id for record in records if record.sent_ns is None}:
        raise ValueError("not-sent requests need matching event evidence")


def validate_capture(raw: object) -> list[RequestRecord]:
    """O(N + E) time and O(N + E) memory for at most 90,000 records and 4,096 events."""
    exact_fields(raw, CAPTURE_FIELDS, "foreground capture")
    bounded_integer(raw["schema_version"], "capture version", 1, 1)
    if raw["status"] != "completed" or raw["socket_error_errno"] is not None:
        raise ValueError("foreground collection did not complete successfully")
    if raw["protocol_status"] != "proposed":
        raise ValueError("unsupported protocol status")
    for key in ("bind", "peer"):
        address = raw[key]
        if not isinstance(address, list) or len(address) != 2:
            raise ValueError("capture endpoints must contain address and port")
        endpoint(*address, allow_isolated=True)
    exact_fields(
        raw["config"], {field.name for field in fields(Workload)}, "foreground configuration"
    )
    plan = Workload(**raw["config"])
    _capture_times(raw, plan)
    records = _capture_records(raw, plan)
    _capture_events(raw, records)
    return records


def _manifest_identity(manifest: dict) -> None:
    exact_fields(manifest, MANIFEST_FIELDS, "manifest")
    bounded_integer(manifest["schema_version"], "manifest version", 1, 1)
    if not isinstance(manifest["started_utc"], str):
        raise ValueError("manifest start must be an ISO timestamp")
    started = datetime.fromisoformat(manifest["started_utc"])
    if started.utcoffset() is None or started.utcoffset().total_seconds() != 0:
        raise ValueError("manifest start timestamp must use UTC")
    if not isinstance(manifest["run_id"], str) or not re.fullmatch(
        r"[a-f0-9]{32}", manifest["run_id"]
    ):
        raise ValueError("invalid run identifier")
    source = exact_fields(manifest["source"], {"commit", "tree_sha256", "dirty"}, "source identity")
    for key, length in (("commit", 40), ("tree_sha256", 64)):
        if not isinstance(source[key], str) or not re.fullmatch(
            rf"[a-f0-9]{{{length}}}", source[key]
        ):
            raise ValueError("invalid source digest")
    if type(source["dirty"]) is not bool:
        raise ValueError("source dirty flag must be boolean")
    if manifest["units"] != {"timestamps": "ns", "goodput": "Mb/s", "cpu": "percent"}:
        raise ValueError("unsupported measurement units")
    if not isinstance(manifest["mode"], str) or manifest["mode"] not in {"loopback", "namespace"}:
        raise ValueError("unsupported topology mode")
    expected = {"none"} if manifest["mode"] == "loopback" else POLICIES
    if not isinstance(manifest["policy"], str) or manifest["policy"] not in expected:
        raise ValueError("policy does not match topology mode")


def _history(manifest: dict) -> None:
    history = manifest["history"]
    if not isinstance(history, list) or not 1 <= len(history) <= 10:
        raise ValueError("invalid lifecycle history")
    previous, observed = "created", 0
    for item in history:
        exact_fields(item, {"state", "observed_ns"}, "history item")
        if not isinstance(item["state"], str) or item["state"] not in TRANSITIONS.get(
            previous, set()
        ):
            raise ValueError("invalid recorded lifecycle transition")
        observed = bounded_integer(
            item["observed_ns"], "transition timestamp", observed, MAX_TIMESTAMP_NS
        )
        previous = item["state"]
    if previous != manifest["state"] or manifest["errors"] != []:
        raise ValueError("lifecycle state is incomplete or contains errors")


def _load_artifacts(directory: Path, manifest: dict) -> dict:
    artifacts = exact_fields(manifest["artifacts"], ARTIFACTS, "artifact hashes")
    loaded = {}
    for name, checksum in artifacts.items():
        if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise ValueError("invalid artifact digest")
        if digest(directory / name) != checksum:
            raise ValueError(f"artifact digest mismatch: {name}")
        loaded[name] = read_json(directory / name)
    return loaded


def _cross_checks(artifacts: dict, manifest: dict) -> None:
    from src.trial import TrialConfig

    config = artifacts["configuration.json"]
    exact_fields(config, {field.name for field in fields(TrialConfig)}, "trial configuration")
    plan = TrialConfig(**config)
    if config["mode"] != manifest["mode"] or config["policy"] != manifest["policy"]:
        raise ValueError("configuration and manifest select different treatments")
    foreground = artifacts["foreground.json"]
    if foreground["config"] != {
        field.name: getattr(plan.foreground_plan(), field.name) for field in fields(Workload)
    }:
        raise ValueError("foreground configuration differs from the trial")
    phases = {
        key: foreground[key] for key in ("start_ns", "measurement_start_ns", "measurement_end_ns")
    }
    phases["end_ns"] = foreground["planned_end_ns"]
    if manifest["phases"] != phases:
        raise ValueError("manifest phase boundaries differ from the capture")
    bulk = exact_fields(
        artifacts["bulk.json"],
        {
            "requested",
            "per_flow_bps",
            "actual_flows",
            "receiver_bytes",
            "receiver_seconds",
            "goodput_mbps",
            "intervals",
            "tool_version",
            "exit_status",
            "window",
            "foreground_window_aligned",
        },
        "bulk summary",
    )
    requested = {
        field.name: getattr(plan.bulk_plan(), field.name) for field in fields(plan.bulk_plan())
    }
    if (
        bulk.get("requested") != requested
        or bulk.get("actual_flows") != plan.flows
        or bulk.get("exit_status") != 0
    ):
        raise ValueError("bulk flow set or requested load differs from the trial")
    _bulk_numbers(bulk)
    if abs(bulk["receiver_seconds"] - plan.measurement_seconds) > 0.25:
        raise ValueError("bulk receiver duration differs from the configured measurement")
    bounded_integer(bulk["actual_flows"], "actual flow count", plan.flows, plan.flows)
    bounded_integer(bulk["exit_status"], "bulk exit status", 0, 0)
    bounded_integer(
        bulk["per_flow_bps"],
        "per-flow pacing",
        plan.bulk_plan().per_flow_bps,
        plan.bulk_plan().per_flow_bps,
    )


def _bulk_numbers(bulk: dict) -> None:
    count = bounded_integer(bulk.get("receiver_bytes"), "bulk bytes", 0, 2**53)
    seconds = bounded_number(bulk.get("receiver_seconds"), "bulk seconds", 0.001, 181)
    goodput = bounded_number(bulk.get("goodput_mbps"), "bulk goodput", 0, 1_000_000)
    if abs(goodput - 8 * count / seconds / 1_000_000) > 1e-9:
        raise ValueError("bulk goodput is inconsistent with receiver bytes and duration")
    if bulk.get("foreground_window_aligned") is not False:
        raise ValueError("this collector does not establish bulk/foreground window alignment")
    if (
        bulk["window"] != "iperf_receiver"
        or not isinstance(bulk["tool_version"], str)
        or not 1 <= len(bulk["tool_version"]) <= 100
    ):
        raise ValueError("bulk window and tool version must be recorded")
    _bulk_intervals(bulk, count, seconds)


def _bulk_intervals(bulk: dict, count: int, seconds: float) -> None:
    rows = bulk["intervals"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 400:
        raise ValueError("invalid receiver interval list")
    total, last = 0, 0.0
    for row in rows:
        exact_fields(row, {"start_seconds", "end_seconds", "bytes"}, "receiver interval")
        start = bounded_number(row["start_seconds"], "interval start", last, 181)
        end = bounded_number(row["end_seconds"], "interval end", start, 181)
        if end <= start or abs(start - last) > 0.01:
            raise ValueError("receiver interval has a gap or no duration")
        total += bounded_integer(row["bytes"], "interval bytes", 0, 2**53)
        last = end
    if total != count or abs(last - seconds) > 0.01:
        raise ValueError("receiver interval totals do not match the summary")


def _supporting_artifacts(artifacts: dict, manifest: dict) -> None:
    cpu = exact_fields(
        artifacts["cpu.json"], {"scope", "busy_percent", "iowait_percent"}, "CPU summary"
    )
    if cpu["scope"] == "unavailable":
        if cpu["busy_percent"] is not None or cpu["iowait_percent"] is not None:
            raise ValueError("unavailable CPU measurement must not have a numeric value")
    elif cpu["scope"] == "shared_host":
        for key in ("busy_percent", "iowait_percent"):
            bounded_number(cpu[key], key, 0, 100)
        if cpu["busy_percent"] + cpu["iowait_percent"] > 100 + 1e-9:
            raise ValueError("CPU percentages exceed the total")
    else:
        raise ValueError("unsupported CPU measurement scope")
    environment = exact_fields(
        artifacts["environment.json"],
        {"system", "kernel", "python", "measurement_kind"},
        "environment",
    )
    if any(
        not isinstance(value, str) or not 1 <= len(value) <= 256 for value in environment.values()
    ):
        raise ValueError("environment values must be bounded strings")
    kind = "loopback_diagnostic" if manifest["mode"] == "loopback" else "virtual_testbed"
    if environment["measurement_kind"] not in {kind, "synthetic_fixture"}:
        raise ValueError("environment does not describe the selected testbed")
    _queues(artifacts, manifest["mode"], manifest["policy"])


def _queues(artifacts: dict, mode: str, policy: str) -> None:
    for name in ("queues-before.json", "queues-after.json"):
        raw = artifacts[name]
        if mode == "loopback":
            if raw != {"kind": "loopback", "network_changes": False, "queue_verified": False}:
                raise ValueError("loopback must not claim queue configuration")
        else:
            exact_fields(
                raw, {"kind", "attachment_checked", "calibrated", "snapshots"}, "queue evidence"
            )
            if (
                raw["kind"] != "virtual_testbed"
                or raw["attachment_checked"] is not True
                or raw["calibrated"] is not False
            ):
                raise ValueError("invalid namespace attachment evidence")
            keys = set(inspection_commands(Topology("000000000000")))
            snapshots = exact_fields(raw["snapshots"], keys, "namespace snapshots")
            if any(not isinstance(value, list) or len(value) > 512 for value in snapshots.values()):
                raise ValueError("namespace snapshots must be bounded lists")
            check_queue_kinds(snapshots["router_queues"], policy)


def validate_contents(directory: Path, manifest: dict) -> dict:
    _manifest_identity(manifest)
    if manifest["state"] not in {"validation", "completed"}:
        raise ValueError("run is incomplete or failed")
    _history(manifest)
    artifacts = _load_artifacts(directory, manifest)
    records = validate_capture(artifacts["foreground.json"])
    _cross_checks(artifacts, manifest)
    _supporting_artifacts(artifacts, manifest)
    validity = exact_fields(manifest["validity"], {"eligible_for_primary", "reasons"}, "validity")
    if validity["eligible_for_primary"] is not False:
        raise ValueError("primary collection requires a separately accepted pilot decision")
    if not isinstance(validity["reasons"], list) or not 1 <= len(validity["reasons"]) <= 20:
        raise ValueError("validity needs bounded reasons")
    if any(
        not isinstance(reason, str) or not 1 <= len(reason) <= 256 for reason in validity["reasons"]
    ):
        raise ValueError("validity reasons must be bounded strings")
    measurement_count = (
        len(records)
        - artifacts["foreground.json"]["config"]["warmup_ms"]
        * artifacts["foreground.json"]["config"]["requests_per_second"]
        // 1000
    )
    return {
        "integrity_valid": True,
        "eligible_for_primary": False,
        "mode": manifest["mode"],
        "policy": manifest["policy"],
        "measurement_requests": measurement_count,
        "not_sent": sum(record.sent_ns is None for record in records),
    }


def validate_bundle(directory: Path) -> dict:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("bundle must be a directory, not a symlink")
    manifest = read_json(directory / "manifest.json", 65536)
    if not isinstance(manifest, dict) or manifest.get("state") != "completed":
        raise ValueError("run did not complete; retain it as failed or incomplete evidence")
    return validate_contents(directory, manifest)
