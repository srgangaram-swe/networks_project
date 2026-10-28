"""Per-run development summaries; these never certify the primary experiment."""

import csv
from pathlib import Path

from src.artifacts import atomic_json, digest, read_json
from src.bundle_validation import validate_bundle, validate_capture

QUANTILES = {"p50_ms": 500, "p95_ms": 950, "p99_ms": 990, "p999_ms": 999}


def nearest_rank(sorted_values: list[int], per_thousand: int) -> float | None:
    if type(per_thousand) is not int or not 1 <= per_thousand <= 1000:
        raise ValueError("quantile must be an integer from 1 to 1000")
    if not sorted_values:
        return None
    rank = (per_thousand * len(sorted_values) + 999) // 1000
    return sorted_values[rank - 1] / 1_000_000


def summarize(directory: Path) -> tuple[dict, list[dict]]:
    """O(N log N) time, O(N) memory. Sort each metric once within each run."""
    validate_bundle(directory)
    manifest = read_json(directory / "manifest.json", 65536)
    capture = read_json(directory / "foreground.json")
    bulk = read_json(directory / "bulk.json")
    environment = read_json(directory / "environment.json")
    if environment["measurement_kind"] == "synthetic_fixture":
        raise ValueError("synthetic fixtures cannot be exported as observed diagnostics")
    warmup_count = capture["config"]["warmup_ms"] * capture["config"]["requests_per_second"] // 1000
    records = validate_capture(capture)[warmup_count:]
    good = sorted(record.rtt_ns for record in records if record.outcome == "on_time")
    lags = sorted(
        record.sent_ns - record.scheduled_ns for record in records if record.sent_ns is not None
    )
    jitter = sorted(
        abs(second.rtt_ns - first.rtt_ns)
        for first, second in zip(records, records[1:], strict=False)
        if first.outcome == second.outcome == "on_time"
    )
    counts = capture["counts"]["measurement"]
    sent = len(records) - counts["not_sent"]
    timeouts = counts["timeout"] + counts["late"]
    summary = {
        "run_id": manifest["run_id"],
        "measurement_kind": environment["measurement_kind"],
        "platform": environment["system"],
        "policy": manifest["policy"],
        "flows": bulk["actual_flows"],
        "scheduled": len(records),
        "sent": sent,
        "on_time": counts["on_time"],
        "timeout_count": timeouts,
        "late_count": counts["late"],
        "not_sent": counts["not_sent"],
        "timeout_rate": timeouts / sent if sent else None,
        "not_sent_rate": counts["not_sent"] / len(records),
        "jitter_pairs": len(jitter),
        "jitter_ms": _median_ms(jitter),
        "send_lag_p99_ms": nearest_rank(lags, 990),
        "requested_mbps": bulk["requested"]["aggregate_bps"] / 1_000_000,
        "goodput_mbps": bulk["goodput_mbps"],
        "p99_censored": timeouts / sent > 0.01 if sent else True,
        "source_commit": manifest["source"]["commit"],
        "source_tree_sha256": manifest["source"]["tree_sha256"],
        "source_dirty": manifest["source"]["dirty"],
        "manifest_sha256": digest(directory / "manifest.json"),
        "eligible_for_primary": False,
    }
    summary.update({name: nearest_rank(good, rank) for name, rank in QUANTILES.items()})
    rows = [
        {
            "run_id": manifest["run_id"],
            "request_id": record.request_id,
            "elapsed_seconds": (record.scheduled_ns - capture["measurement_start_ns"]) / 1e9,
            "outcome": record.outcome,
            "rtt_ms": None if record.rtt_ns is None else record.rtt_ns / 1e6,
            "send_lag_ms": None
            if record.sent_ns is None
            else (record.sent_ns - record.scheduled_ns) / 1e6,
        }
        for record in records
    ]
    return summary, rows


def _median_ms(values: list[int]) -> float | None:
    if not values:
        return None
    middle = len(values) // 2
    return (values[middle] + values[(len(values) - 1) // 2]) / 2_000_000


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def export_diagnostics(directories: list[Path], destination: Path) -> dict:
    if not 1 <= len(directories) <= 20:
        raise ValueError("export between 1 and 20 diagnostic runs")
    summaries, series = [], []
    for directory in directories:
        summary, rows = summarize(directory)
        summaries.append(summary)
        if len(series) + len(rows) > 200_000:
            raise ValueError("diagnostic export exceeds 200,000 request rows")
        series.extend(rows)
    if len({summary["run_id"] for summary in summaries}) != len(summaries):
        raise ValueError("duplicate run in diagnostic export")
    destination.mkdir(mode=0o755)
    _write_csv(destination / "summary.csv", summaries)
    _write_csv(destination / "requests.csv", series)
    provenance = {
        "schema_version": 1,
        "purpose": "development_diagnostics",
        "run_count": len(summaries),
        "request_count": len(series),
        "eligible_for_primary": False,
        "summary_sha256": digest(destination / "summary.csv"),
        "requests_sha256": digest(destination / "requests.csv"),
    }
    atomic_json(destination / "provenance.json", provenance)
    return provenance
