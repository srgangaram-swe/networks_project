"""Bounded table exports with a full schedule and checked per-run input files."""

import csv
import platform
import re
from pathlib import Path

from src.artifacts import atomic_json, digest, read_bytes, read_json
from src.simulation import REQUEST_FIELDS


def export_run_tables(output: Path, collection: Path, plan: dict, trials: list[dict]) -> None:
    if not 1 <= len(trials) <= 400:
        raise ValueError("table export requires one to 400 runs")
    known = {cell["cell_id"] for cell in plan["schedule"]["cells"]}
    if len({row["cell_id"] for row in trials}) != len(trials) or any(
        row["cell_id"] not in known or row["state"] != "completed" for row in trials
    ):
        raise ValueError("table export requires unique completed planned cells")
    output.mkdir(mode=0o700)
    attempts = [
        {
            "cell_id": row["cell_id"],
            "status": "completed",
            "manifest_sha256": row["manifest_sha256"],
            "derived_table_hashes": row["table_hashes"],
        }
        for row in trials
    ]
    design = {"plan": plan, "attempts": attempts, "eligible_for_primary": False}
    atomic_json(output / "attempts.json", design)
    atomic_json(
        output / "versions.json", {"python": platform.python_version(), "system": platform.system()}
    )
    index = {
        "schema_version": 1,
        "kind": "diagnostic_export_batches",
        "state": "writing",
        "eligible_for_primary": False,
        "attempts_sha256": digest(output / "attempts.json"),
        "versions_sha256": digest(output / "versions.json"),
        "batches": [],
    }
    atomic_json(output / "index.json", index)
    batch_size = min(16, 200000 // (plan["configuration"]["measurement_seconds"] * 500))
    for start in range(0, len(trials), batch_size):
        chunk = trials[start : start + batch_size]
        name = f"batch-{len(index['batches']) + 1:03d}"
        _batch(output / name, collection, plan, chunk, index["attempts_sha256"])
        index["batches"].append(
            {"directory": name, "provenance_sha256": digest(output / name / "provenance.json")}
        )
        atomic_json(output / "index.json", index)
    index["state"] = "completed"
    atomic_json(output / "index.json", index)


def _batch(output, collection, plan, trials, ledger_hash):
    summaries = []
    for trial in trials:
        if not isinstance(trial["directory"], str) or not re.fullmatch(
            r"trial-[0-9]{1,3}", trial["directory"]
        ):
            raise ValueError("trial directory must be a bounded relative name")
        path = collection / trial["directory"]
        if path.is_symlink() or not path.is_dir():
            raise ValueError("trial directory must be a real directory")
        if digest(path / "manifest.json") != trial["manifest_sha256"]:
            raise ValueError("trial manifest changed before export")
        row = read_json(path / "summary.json", 65536)
        if row["manifest_sha256"] != trial["manifest_sha256"]:
            raise ValueError("summary manifest binding changed")
        for name in ("summary", "requests"):
            extension = "json" if name == "summary" else "csv"
            if digest(path / f"{name}.{extension}") != trial["table_hashes"][name]:
                raise ValueError("derived trial table changed before export")
        summaries.append(row)
    output.mkdir(mode=0o700)
    with (output / "summary.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, list(summaries[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(summaries)
    count = _requests(output, collection, trials)
    design = {
        "plan": plan,
        "attempts": [
            {
                "cell_id": r["cell_id"],
                "status": "completed",
                "manifest_sha256": r["manifest_sha256"],
            }
            for r in trials
        ],
        "campaign_ledger_sha256": ledger_hash,
    }
    atomic_json(output / "attempts.json", design)
    atomic_json(
        output / "provenance.json",
        {
            "schema_version": 1,
            "purpose": "simulation"
            if plan["kind"] == "local_simulation"
            else "development_diagnostics",
            "eligible_for_primary": False,
            "run_count": len(trials),
            "request_count": count,
            "summary_sha256": digest(output / "summary.csv"),
            "requests_sha256": digest(output / "requests.csv"),
            "attempts_sha256": digest(output / "attempts.json"),
        },
    )


def _requests(output, collection, trials):
    count = 0
    with (output / "requests.csv").open("xb") as stream:
        stream.write((",".join(REQUEST_FIELDS) + "\n").encode())
        for trial in trials:
            data = read_bytes(collection / trial["directory"] / "requests.csv", 8 * 1024 * 1024)
            header, rows = data.split(b"\n", 1)
            if header != ",".join(REQUEST_FIELDS).encode():
                raise ValueError("unsupported request table columns")
            count += rows.count(b"\n")
            if count > 200000:
                raise ValueError("batch exceeds 200,000 request rows")
            stream.write(rows)
    return count
