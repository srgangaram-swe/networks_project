"""Serial physical trials with client-clock coordination and checked artifact retrieval."""

import csv
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from threading import Event

from src.artifacts import atomic_json, digest, parse_json, read_json
from src.bundle_validation import ARTIFACTS, OPTIONAL_ARTIFACTS, validate_bundle
from src.campaign import resolve_trials
from src.diagnostics import summarize
from src.physical_profile import (
    check_inspections,
    host_command,
    payload,
    validate_profile,
    worker_command,
)
from src.processes import run_command
from src.run_bundle import source_identity
from src.simulation import REQUEST_FIELDS
from src.trial import ROOT, TrialConfig


def trial_command(profile: dict, action: str, request: dict) -> tuple[str, ...]:
    item = profile["roles"]["client"]
    root = Path(item["repository"])
    return host_command(
        item,
        (
            str(root / ".venv/bin/python"),
            str(root / "scripts/physical_trial.py"),
            action,
            "--request",
            payload(request),
        ),
    )


def preflight(profile: dict) -> dict:
    validate_profile(profile)
    expected = source_identity(ROOT)
    identities = {}
    inspections = []
    token = uuid.uuid4().hex[:12]
    for role, item in profile["roles"].items():
        root = Path(item["repository"])
        command = host_command(
            item,
            (
                str(root / ".venv/bin/python"),
                str(root / "scripts/physical_trial.py"),
                "identity",
                "--request",
                payload({"role": role, "item": item}),
            ),
        )
        actual = parse_json(run_command(command, timeout=30).stdout)
        if (actual["commit"], actual["tree_sha256"]) != (
            expected["commit"],
            expected["tree_sha256"],
        ):
            raise ValueError(f"{role} source differs; update all hosts to the same tested revision")
        inspections.append(
            parse_json(
                run_command(worker_command(profile, role, "inspect", token), timeout=30).stdout
            )
        )
        identities[role] = actual
    check_inspections(inspections)
    return identities


def physical_plan(raw: dict, source: dict, *, transport="udp", shadow_forecast=False) -> dict:
    schedule, _ = resolve_trials(
        raw, 10, diagnostic_matrix=True, transport=transport, shadow_forecast=shadow_forecast
    )
    if raw["measurement_seconds"] > 60:
        raise ValueError("physical diagnostics support at most 280 cells and 60 measured seconds")
    return {
        "kind": "physical_testbed_diagnostics",
        "configuration": raw,
        "schedule": schedule,
        "source": source,
        "transport": transport,
        "shadow_forecast": shadow_forecast,
        "eligible_for_primary": False,
    }


def collect_physical(
    directory: Path, plan: dict, profile: dict, cancel: Event, notify
) -> list[dict]:
    directory.mkdir(mode=0o700)
    trials = []
    for index, cell in enumerate(plan["schedule"]["cells"], 1):
        if cancel.is_set():
            raise InterruptedError("physical campaign cancelled before the next trial")
        token = uuid.uuid4().hex[:12]
        config = TrialConfig(
            mode="physical",
            policy=cell["policy"],
            measurement_seconds=plan["configuration"]["measurement_seconds"],
            warmup_seconds=10,
            flows=cell["flows"],
            aggregate_bps=round(cell["load_fraction"] * 100_000_000),
            transport=plan.get("transport", "udp"),
            shadow_forecast=plan.get("shadow_forecast", False),
        )
        request = {"profile": profile, "token": token, "configuration": asdict(config)}
        notify("trial_started", trial=index, policy=cell["policy"], block=cell["block"])
        started = time.monotonic()
        local = directory / f"trial-{index:03d}"
        local.mkdir(mode=0o700)
        atomic_json(local / "remote-request.json", request)
        try:
            run_command(trial_command(profile, "run", request), timeout=300, stop=cancel)
            _retrieve(local, profile, token)
            _check_treatment(local, plan["source"], config)
            summary, rows = summarize(local)
            atomic_json(local / "summary.json", summary)
            with (local / "requests.csv").open("x", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, REQUEST_FIELDS, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            trial = {
                "directory": local.name,
                "cell_id": cell["cell_id"],
                "state": "completed",
                "manifest_sha256": digest(local / "manifest.json"),
                "wall_seconds": time.monotonic() - started,
                "table_hashes": {
                    "summary": digest(local / "summary.json"),
                    "requests": digest(local / "requests.csv"),
                },
            }
            trials.append(trial)
            atomic_json(directory / "progress.json", {"state": "running", "trials": trials})
            notify("trial_completed", trial=index, wall_seconds=trial["wall_seconds"])
        except BaseException as error:
            try:
                atomic_json(
                    local / "failure.json",
                    {
                        "error_type": type(error).__name__,
                        "token": token,
                        "message": str(error)[:1024],
                        "remote_evidence_retained": True,
                    },
                )
            except (OSError, ValueError) as persistence:
                error.add_note(f"retaining remote failure details also failed: {persistence}")
            raise
    atomic_json(directory / "progress.json", {"state": "completed", "trials": trials})
    return trials


def _retrieve(local: Path, profile: dict, token: str):
    def fetch(name):
        request = {"profile": profile, "token": token, "artifact": name}
        result = run_command(
            trial_command(profile, "fetch", request), timeout=30, limit=32 * 1024 * 1024
        )
        with (local / name).open("xb") as stream:
            stream.write(result.stdout)

    fetch("manifest.json")
    manifest = read_json(local / "manifest.json", 65536)
    names = manifest.get("artifacts")
    if (
        not isinstance(names, dict)
        or not ARTIFACTS <= names.keys()
        or not names.keys() <= ARTIFACTS | OPTIONAL_ARTIFACTS
    ):
        raise ValueError("remote manifest contains missing or unexpected artifact names")
    for name in sorted(names):
        fetch(name)
    validate_bundle(local)
    actual = read_json(local / "manifest.json", 65536)["mode"]
    if actual != "physical":
        raise ValueError("retrieved trial is not a physical measurement")


def _check_treatment(local, source, config):
    manifest = read_json(local / "manifest.json", 65536)
    actual = manifest["source"]
    if any(actual[name] != source[name] for name in ("commit", "tree_sha256")):
        raise ValueError("retrieved trial source differs from the campaign plan")
    if read_json(local / "configuration.json", 65536) != asdict(config):
        raise ValueError("retrieved trial treatment differs from its planned cell")
