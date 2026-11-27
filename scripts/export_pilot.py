"""Export validated diagnostic observations and account for every attempted cell."""

import argparse
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.artifacts import atomic_json, digest, read_json  # noqa: E402
from src.campaign import PLAN_BYTES, PROGRESS_BYTES, resolve_plan  # noqa: E402
from src.diagnostics import export_diagnostics  # noqa: E402
from src.processes import run_command  # noqa: E402


def export(campaign: Path, output: Path) -> None:
    plan = read_json(campaign / "plan.json", PLAN_BYTES)
    progress = read_json(campaign / "progress.json", PROGRESS_BYTES)
    if digest(campaign / "plan.json") != progress["plan_sha256"]:
        raise ValueError("retained campaign plan changed")
    if (
        type(progress["schema_version"]) is not int
        or progress["schema_version"] != 1
        or progress["state"] not in {"ready", "running", "stopped", "completed"}
    ):
        raise ValueError("unsupported campaign progress")
    schedule, _ = resolve_plan(plan)
    cells = {cell["cell_id"] for cell in schedule["cells"]}
    attempts, directories = _retained_attempts(campaign, progress, cells)
    design = {
        "schema_version": 1,
        "campaign_state": progress["state"],
        "attempts": attempts,
        "unattempted_cells": sorted(cells - {attempt["cell_id"] for attempt in attempts}),
        "plan": plan,
        "progress_sha256": digest(campaign / "progress.json"),
        "primary_eligible": False,
        "excluded_from_primary": "pilot_review_and_window_alignment_pending",
    }
    batch_size = min(
        20,
        200000
        // (
            plan["configuration"]["measurement_seconds"]
            * plan["configuration"]["foreground_requests_per_second"]
        ),
    )
    if len(directories) > batch_size:
        _export_batches(output, directories, design, batch_size)
        return
    _export_one(output, directories, design)


def _retained_attempts(campaign, progress, cells):
    attempts, directories = [], []
    completed = set()
    if not isinstance(progress["attempts"], list) or len(progress["attempts"]) > 3 * len(cells):
        raise ValueError("invalid attempt count")
    for index, attempt in enumerate(progress["attempts"]):
        cell = attempt["cell_id"]
        if cell not in cells:
            raise ValueError("attempt does not belong to the planned schedule")
        name = f"attempt-{index + 1:03d}-{cell}"
        if attempt["directory"] != name:
            raise ValueError("invalid attempt directory")
        if attempt["status"] not in {"running", "failed", "completed"}:
            raise ValueError("unsupported attempt status")
        if attempt["status"] == "completed":
            if cell in completed:
                raise ValueError("multiple completed attempts for one cell")
            if digest(campaign / name / "manifest.json") != attempt["manifest_sha256"]:
                raise ValueError("completed attempt digest changed")
            directories.append(campaign / name)
            completed.add(cell)
        attempts.append(attempt)
    return attempts, directories


def _export_one(output: Path, directories: list[Path], design: dict) -> None:
    if directories:
        export_diagnostics(directories, output)
    else:
        output.mkdir(mode=0o700)
    atomic_json(output / "attempts.json", design)
    atomic_json(output / "versions.json", tool_versions())
    _bind_design(output, bool(directories))


def _export_batches(output, directories, design, batch_size):
    """Keep each batch below both row limits; retain the full failed-attempt ledger."""
    output.mkdir(mode=0o700)
    atomic_json(output / "attempts.json", design)
    atomic_json(output / "versions.json", tool_versions())
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
    for start in range(0, len(directories), batch_size):
        chunk = directories[start : start + batch_size]
        names = {path.name for path in chunk}
        subset = {
            **design,
            "campaign_ledger_sha256": index["attempts_sha256"],
            "attempts": [
                a
                for a in design["attempts"]
                if a["status"] != "completed" or a["directory"] in names
            ],
        }
        name = f"batch-{len(index['batches']) + 1:03d}"
        _export_one(output / name, chunk, subset)
        index["batches"].append(
            {
                "directory": name,
                "provenance_sha256": digest(output / name / "provenance.json"),
            }
        )
        atomic_json(output / "index.json", index)
    index["state"] = "completed"
    atomic_json(output / "index.json", index)


def _bind_design(output: Path, has_observations: bool) -> None:
    """Bind schedule metadata to the same export as the validated observations."""
    if has_observations:
        provenance = read_json(output / "provenance.json", 65536)
        provenance["attempts_sha256"] = digest(output / "attempts.json")
        atomic_json(output / "provenance.json", provenance)


def tool_versions() -> dict:
    versions = {}
    for name, args in (
        ("iproute2", ("tc", "-V")),
        ("iperf3", ("iperf3", "--version")),
        ("tcpdump", ("tcpdump", "--version")),
        ("ethtool", ("ethtool", "--version")),
    ):
        result = run_command(args, limit=8192)
        versions[name] = (result.stdout or result.stderr).decode("utf-8").splitlines()[0][:512]
    return {
        "system": platform.system(),
        "kernel": platform.release(),
        "python": platform.python_version(),
        "tools": versions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        export(args.campaign, args.output)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f"Pilot export failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
