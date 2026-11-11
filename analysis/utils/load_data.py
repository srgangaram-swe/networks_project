"""Bounded, checked diagnostic exports for Jonathan's comparison workflow."""

import csv
import gzip
import hashlib
import io
import math
import zlib
from pathlib import Path

import pandas as pd

from analysis.utils.validate_data import validate_requests, validate_summaries
from src.artifacts import MAX_JSON_BYTES, json_bytes, parse_json, read_bytes
from src.experiment_config import ExperimentConfig
from src.schedule import make_schedule


def _csv(path: Path, checksum: str, limit: int) -> pd.DataFrame:
    data = _csv_bytes(path)
    if hashlib.sha256(data).hexdigest() != checksum:
        raise ValueError(f"{path.name} hash does not match provenance")
    header = next(csv.reader(io.StringIO(data.decode("utf-8"))), [])
    if not header or len(header) != len(set(header)):
        raise ValueError("CSV headers must be nonempty and unique")
    frame = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, nrows=limit + 1)
    if len(frame) > limit:
        raise ValueError(f"{path.name} exceeds its {limit}-row limit")
    return frame


def _csv_bytes(path: Path) -> bytes:
    compressed = path.with_suffix(path.suffix + ".gz")
    if path.exists() or path.is_symlink():
        if compressed.exists() or compressed.is_symlink():
            raise ValueError("choose either plain or compressed CSV, not both")
        return read_bytes(path)
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(read_bytes(compressed))) as stream:
            data = stream.read(MAX_JSON_BYTES + 1)
    except (gzip.BadGzipFile, EOFError, zlib.error) as error:
        raise ValueError("invalid or truncated compressed CSV") from error
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("expanded CSV exceeds the 32 MiB file limit")
    return data


def attach_design(summaries: pd.DataFrame, design: dict) -> pd.DataFrame:
    """Bind completed manifests to recorded schedule cells, never infer blocks."""
    plan = design["plan"]
    schedule = make_schedule(ExperimentConfig.from_mapping(plan["configuration"]))
    if schedule != plan["schedule"]:
        raise ValueError("recorded schedule differs from configuration")
    cells = {cell["cell_id"]: cell for cell in schedule["cells"]}
    attempts = design["attempts"]
    if not isinstance(attempts, list) or len(attempts) > 840:
        raise ValueError("invalid attempt ledger size")
    completed = [row for row in attempts if row["status"] == "completed"]
    if len(completed) != len(summaries):
        raise ValueError("completed attempts do not match exported runs")
    by_digest = {row["manifest_sha256"]: row for row in completed}
    if len(by_digest) != len(completed):
        raise ValueError("duplicate completed manifest")
    cohort = hashlib.sha256(json_bytes(plan)).hexdigest()
    rows = [
        _design_row(row, by_digest, cells, plan["source"], cohort)
        for row in summaries.to_dict("records")
    ]
    result = pd.DataFrame(rows)
    if result["cell_id"].duplicated().any():
        raise ValueError("multiple completed attempts for one cell")
    return result


def _design_row(row, by_digest, cells, source, cohort):
    attempt = by_digest[row["manifest_sha256"]]
    cell = cells[attempt["cell_id"]]
    expected = (cell["policy"], cell["flows"], cell["load_fraction"] * 100)
    actual = (row["policy"], row["flows"], row["requested_mbps"])
    if actual[:2] != expected[:2] or not math.isclose(actual[2], expected[2], abs_tol=1e-9):
        raise ValueError("run condition differs from recorded schedule")
    if (row["source_commit"], row["source_tree_sha256"], row["source_dirty"]) != (
        source["commit"],
        source["tree_sha256"],
        source["dirty"],
    ):
        raise ValueError("run source differs from recorded campaign")
    return {
        **row,
        "block": f"{cohort}:{cell['block']}",
        "cell_id": cell["cell_id"],
        "baseline_id": cell["baseline_id"],
        "cohort": cohort,
    }


def load_data(export_dir: str | Path, *, binding: dict | None = None):
    """At most 20 runs and 200,000 requests per export; O(bytes + N log N)."""
    directory = Path(export_dir)
    raw_provenance = read_bytes(directory / "provenance.json", 65536)
    binding = binding or {}
    if binding and hashlib.sha256(raw_provenance).hexdigest() != binding["provenance_sha256"]:
        raise ValueError("batch provenance hash does not match export index")
    provenance = parse_json(raw_provenance)
    if (
        type(provenance["schema_version"]) is not int
        or provenance["schema_version"] != 1
        or provenance["eligible_for_primary"] is not False
    ):
        raise ValueError("expected a schema-v1 diagnostic export, ineligible for primary use")
    summaries = _csv(directory / "summary.csv", provenance["summary_sha256"], 20)
    requests = _csv(directory / "requests.csv", provenance["requests_sha256"], 200000)
    if (len(summaries), len(requests)) != (provenance["run_count"], provenance["request_count"]):
        raise ValueError("export row counts do not match provenance")
    validate_summaries(summaries)
    validate_requests(requests, summaries)
    if (directory / "attempts.json").exists():
        data = read_bytes(directory / "attempts.json")
        checksum = hashlib.sha256(data).hexdigest()
        if provenance.get("attempts_sha256", checksum) != checksum:
            raise ValueError("attempt ledger hash does not match provenance")
        provenance = {
            **provenance,
            "design_sha256": checksum,
            "design_bound_to_export": "attempts_sha256" in provenance,
        }
        design = parse_json(data)
        if binding and design.get("campaign_ledger_sha256") != binding["campaign_ledger_sha256"]:
            raise ValueError("batch design does not match campaign ledger")
        summaries = attach_design(summaries, design)
        provenance["planned_cells"] = len(design["plan"]["schedule"]["cells"])
        provenance["noncompleted_attempts"] = sum(
            a["status"] != "completed" for a in design["attempts"]
        )
    provenance["export_provenance_sha256"] = hashlib.sha256(raw_provenance).hexdigest()
    provenance.update(binding)
    requests = requests.merge(summaries[["run_id", "policy"]], on="run_id", validate="many_to_one")
    return summaries, requests, provenance
