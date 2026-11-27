"""Recompute RPC call statistics and reconcile every scheduled admission."""

from dataclasses import fields, replace

from src.basic_rpc_protocol.rpc_metrics import RpcCallRecord, RpcMetrics
from src.experiment_config import bounded_integer, bounded_number

RPC_ARTIFACTS = {"rpc.json", "rpc-server.json", "rpc-bulk.json", "rpc-bulk-raw.json"}


def validate_rpc(raw):
    if (
        not isinstance(raw, dict)
        or type(raw.get("schema_version")) is not int
        or raw["schema_version"] != 1
    ):
        raise ValueError("unsupported RPC evidence")
    if raw.get("eligible_for_primary") is not False or (
        raw.get("purpose"),
        raw.get("eligible_for_primary"),
        raw.get("status"),
    ) != (
        "rpc_development_diagnostics",
        False,
        "completed",
    ):
        raise ValueError("RPC workload did not complete as diagnostic evidence")
    rate = bounded_integer(raw.get("requests_per_second"), "RPC rate", 1, 1000)
    seconds = bounded_integer(raw.get("measurement_seconds"), "RPC seconds", 1, 120)
    scheduled = bounded_integer(raw.get("scheduled_calls"), "scheduled calls", 1, 100000)
    counts = [
        bounded_integer(raw.get(key), key, 0, scheduled)
        for key in (
            "admitted_calls",
            "skipped_capacity",
            "cancelled_before_admission",
        )
    ]
    if scheduled != rate * seconds or sum(counts) != scheduled or counts[2]:
        raise ValueError("RPC admission counts do not reconcile")
    rows = raw.get("requests")
    if not isinstance(rows, list) or len(rows) != counts[0]:
        raise ValueError("RPC records do not match admitted calls")
    metrics = RpcMetrics(max_records=scheduled)
    names = {field.name for field in fields(RpcCallRecord)}
    for row in rows:
        record = RpcCallRecord(**{name: row[name] for name in names})
        if row["duration_ms"] != record.duration_ns / 1e6:
            raise ValueError("RPC duration differs from its timestamps")
        bounded_number(row["start_lag_ms"], "RPC start lag", 0, 200000)
        metrics.add(record)
    bounded_integer(raw.get("workers"), "RPC workers", 1, 256)
    bounded_integer(raw.get("machine_id"), "RPC machine", 0, 2**64 - 1)
    if any(row["machine_id"] != raw["machine_id"] for row in rows):
        raise ValueError("RPC records contain a different machine identifier")
    if raw.get("max_start_lag_ms") != max((row["start_lag_ms"] for row in rows), default=0):
        raise ValueError("RPC start lag differs from retained calls")
    summary = raw["summary"]
    if summary != metrics.summarize(client_counts=summary.get("client_counts")):
        raise ValueError("RPC summary differs from retained calls")
    return summary


def validate_rpc_artifacts(artifacts, plan):
    present = RPC_ARTIFACTS & artifacts.keys()
    if not plan.rpc_diagnostics:
        if present:
            raise ValueError("unplanned RPC artifacts")
        return
    expected = RPC_ARTIFACTS if plan.flows else RPC_ARTIFACTS - {"rpc-bulk-raw.json"}
    if present != expected:
        raise ValueError("RPC phase has missing artifacts")
    raw = artifacts["rpc.json"]
    validate_rpc(raw)
    seconds = min(plan.measurement_seconds, 60)
    if (raw["measurement_seconds"], raw["requests_per_second"], raw["payload_bytes"]) != (
        seconds,
        500,
        482,
    ):
        raise ValueError("RPC workload differs from its planned phase")
    server = artifacts["rpc-server.json"]
    if server.get("status") not in {"completed", "cancelled"} or server.get("socket_error_errno"):
        raise ValueError("RPC server failed")
    from src.bulk import summarize_bulk
    from src.trial import unloaded_summary

    bulk = replace(plan, measurement_seconds=seconds, warmup_seconds=0)
    expected_bulk = (
        summarize_bulk(artifacts["rpc-bulk-raw.json"], bulk.bulk_plan())
        if plan.flows
        else unloaded_summary(bulk)
    )
    if artifacts["rpc-bulk.json"] != expected_bulk:
        raise ValueError("RPC background summary differs from its receiver evidence")
