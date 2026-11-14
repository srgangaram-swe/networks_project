"""Execute a bounded diagnostic schedule while retaining every attempted cell."""

import fcntl
import os
import stat
from dataclasses import asdict
from pathlib import Path
from threading import Event

from src.artifacts import atomic_json, digest, read_json
from src.bundle_validation import validate_bundle
from src.experiment_config import ExperimentConfig, bounded_integer
from src.run_bundle import source_identity
from src.schedule import make_schedule
from src.trial import ROOT, TrialConfig, run_trial

MAX_PILOT_CELLS = 40
MAX_MATRIX_CELLS = 280
PLAN_BYTES = 262144
# Up to 840 attempts, including two 1,024-character notes per attempt.
# Escaped non-BMP characters can use twelve bytes per character.
PROGRESS_BYTES = 32 * 1024 * 1024


def resolve_trials(
    raw: dict,
    warmup_seconds: int,
    *,
    diagnostic_matrix: bool = False,
    transport: str = "udp",
    shadow_forecast: bool = False,
) -> tuple[dict, list[TrialConfig]]:
    config = ExperimentConfig.from_mapping(raw)
    bounded_integer(warmup_seconds, "warmup_seconds", 0, 60)
    if (
        config.link_rate_mbps,
        config.base_rtt_ms,
        config.foreground_message_bytes,
        config.foreground_requests_per_second,
    ) != (100, 20, 512, 500):
        raise ValueError("the executable topology requires 100 Mb/s, 20 ms, 512 bytes, and 500 rps")
    limit = MAX_MATRIX_CELLS if diagnostic_matrix else MAX_PILOT_CELLS
    if config.total_runs > limit:
        raise ValueError(
            f"diagnostic execution is limited to {limit} cells; primary collection is not approved"
        )
    schedule = make_schedule(config)
    trials = [
        TrialConfig(
            mode="namespace",
            policy=cell["policy"],
            measurement_seconds=config.measurement_seconds,
            warmup_seconds=warmup_seconds,
            flows=cell["flows"],
            aggregate_bps=round(cell["load_fraction"] * 100_000_000),
            transport=transport,
            shadow_forecast=shadow_forecast,
        )
        for cell in schedule["cells"]
    ]
    return schedule, trials


def create_campaign(
    directory: Path,
    raw: dict,
    warmup_seconds: int = 10,
    *,
    diagnostic_matrix: bool = False,
    transport: str = "udp",
    shadow_forecast: bool = False,
) -> None:
    schedule, _ = resolve_trials(
        raw,
        warmup_seconds,
        diagnostic_matrix=diagnostic_matrix,
        transport=transport,
        shadow_forecast=shadow_forecast,
    )
    source = source_identity(ROOT)
    directory.mkdir(mode=0o700)
    atomic_json(
        directory / "plan.json",
        {
            "schema_version": 2,
            "transport": transport,
            "shadow_forecast": shadow_forecast,
            "kind": (
                "virtual_testbed_diagnostic_matrix"
                if diagnostic_matrix
                else "virtual_testbed_pilot"
            ),
            "configuration": raw,
            "warmup_seconds": warmup_seconds,
            "source": source,
            "schedule": schedule,
        },
    )
    atomic_json(
        directory / "progress.json",
        {
            "schema_version": 1,
            "plan_sha256": digest(directory / "plan.json"),
            "state": "ready",
            "attempts": [],
        },
    )


def resolve_plan(plan: dict) -> tuple[dict, list[TrialConfig]]:
    """The retained plan selects the execution bound, including on resume."""
    if (
        not isinstance(plan, dict)
        or plan.keys()
        != (
            {"schema_version", "kind", "configuration", "warmup_seconds", "source", "schedule"}
            | ({"transport", "shadow_forecast"} if plan.get("schema_version") == 2 else set())
        )
        or type(plan["schema_version"]) is not int
        or plan["schema_version"] not in (1, 2)
        or plan["kind"] not in {"virtual_testbed_pilot", "virtual_testbed_diagnostic_matrix"}
    ):
        raise ValueError("unsupported campaign plan")
    schedule, trials = resolve_trials(
        plan["configuration"],
        plan["warmup_seconds"],
        diagnostic_matrix=plan["kind"] == "virtual_testbed_diagnostic_matrix",
        transport=plan.get("transport", "udp"),
        shadow_forecast=plan.get("shadow_forecast", False),
    )
    if plan["schedule"] != schedule:
        raise ValueError("retained schedule does not match the configuration")
    return schedule, trials


def _load(directory: Path) -> tuple[dict, dict, list[TrialConfig]]:
    plan = read_json(directory / "plan.json", PLAN_BYTES)
    progress = read_json(directory / "progress.json", PROGRESS_BYTES)
    schedule, trials = resolve_plan(plan)
    if plan["source"] != source_identity(ROOT):
        raise ValueError(
            "campaign schedule or source changed; start a separately identified campaign"
        )
    if (
        not isinstance(progress, dict)
        or progress.keys() != {"schema_version", "plan_sha256", "state", "attempts"}
        or type(progress["schema_version"]) is not int
        or progress["schema_version"] != 1
    ):
        raise ValueError("unsupported campaign progress")
    if progress["plan_sha256"] != digest(directory / "plan.json"):
        raise ValueError("campaign plan digest changed")
    if progress["state"] not in {"ready", "running", "stopped", "completed"}:
        raise ValueError("unsupported campaign state")
    _check_attempts(directory, progress["attempts"], schedule["cells"])
    planned = {
        cell["cell_id"]: trial for cell, trial in zip(schedule["cells"], trials, strict=True)
    }
    for attempt in progress["attempts"]:
        if attempt["status"] == "completed":
            _check_completed(
                directory / attempt["directory"], planned[attempt["cell_id"]], plan["source"]
            )
    return plan, progress, trials


def _check_attempts(directory: Path, attempts: object, cells: list[dict]) -> None:
    if not isinstance(attempts, list) or len(attempts) > 3 * len(cells):
        raise ValueError("campaign exceeds three attempts per cell")
    known = {cell["cell_id"] for cell in cells}
    latest = {}
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict) or attempt.keys() != {
            "cell_id",
            "directory",
            "status",
            "replaces",
            "reason",
            "manifest_sha256",
            "error",
        }:
            raise ValueError("invalid campaign attempt")
        cell = attempt["cell_id"]
        if cell not in known or attempt["directory"] != f"attempt-{index + 1:03d}-{cell}":
            raise ValueError("invalid attempt identity or directory")
        if attempt["status"] not in {"running", "failed", "completed"}:
            raise ValueError("invalid attempt state")
        prior = latest.get(cell)
        if attempt["replaces"] != prior:
            raise ValueError("replacement does not reference the previous attempt")
        if prior is not None and (
            attempts[prior]["status"] == "completed" or not attempt["reason"]
        ):
            raise ValueError("completed attempts cannot be replaced; failures need a reason")
        _check_attempt_evidence(directory, attempt)
        latest[cell] = index


def _check_attempt_evidence(directory: Path, attempt: dict) -> None:
    for key in ("reason", "error"):
        if not isinstance(attempt[key], str) or len(attempt[key]) > 1024:
            raise ValueError("attempt notes must be bounded strings")
    run = directory / attempt["directory"]
    ownership = run / "topology" / "ownership.json"
    if ownership.exists() and read_json(ownership, 65536).get("owned") != {}:
        raise ValueError(
            "an earlier attempt still owns namespaces; inspect and clean it before resuming"
        )
    checksum = attempt["manifest_sha256"]
    if checksum is not None and digest(run / "manifest.json") != checksum:
        raise ValueError("retained attempt manifest changed")
    if attempt["status"] == "completed":
        if checksum is None:
            raise ValueError("completed attempt has no manifest digest")


def _check_completed(directory: Path, trial: TrialConfig, source: dict) -> None:
    validate_bundle(directory)
    if read_json(directory / "configuration.json") != asdict(trial):
        raise ValueError("completed bundle does not match its planned cell")
    if read_json(directory / "manifest.json", 65536)["source"] != source:
        raise ValueError("completed bundle source differs from the campaign")


def _next_attempt(progress: dict, cell: dict, reason: str) -> dict | None:
    attempts = progress["attempts"]
    previous = [
        index for index, attempt in enumerate(attempts) if attempt["cell_id"] == cell["cell_id"]
    ]
    prior = previous[-1] if previous else None
    if prior is not None and attempts[prior]["status"] == "completed":
        return None
    if len(previous) >= 3:
        raise ValueError("three-attempt limit reached; retain evidence and investigate")
    if prior is not None and not reason:
        raise ValueError("a failed or interrupted attempt needs an explicit replacement reason")
    attempt = {
        "cell_id": cell["cell_id"],
        "directory": f"attempt-{len(attempts) + 1:03d}-{cell['cell_id']}",
        "status": "running",
        "replaces": prior,
        "reason": reason if prior is not None else "",
        "manifest_sha256": None,
        "error": "",
    }
    attempts.append(attempt)
    return attempt


def _execute(
    directory: Path, trial: TrialConfig, attempt: dict, cancel: Event, source: dict
) -> None:
    run = directory / attempt["directory"]
    primary_error = None
    try:
        # Successful teardown leaves the campaign's cancellation event clear.
        # A failure stops execution before another cell can start.
        run_trial(run, trial, cancel)
        _check_completed(run, trial, source)
        attempt["status"] = "completed"
    except (OSError, ValueError, RuntimeError, TimeoutError, KeyboardInterrupt) as exc:
        attempt["status"] = "failed"
        attempt["error"] = f"{type(exc).__name__}: {exc}"[:1024]
        primary_error = exc
        raise
    finally:
        try:
            manifest = run / "manifest.json"
            if manifest.exists():
                attempt["manifest_sha256"] = digest(manifest)
        except (OSError, ValueError) as exc:
            if primary_error is None:
                raise
            primary_error.add_note(f"Retaining the attempt digest also failed: {exc}")


def execute_campaign(
    directory: Path, *, replacement_reason: str = "", cancel: Event | None = None
) -> dict:
    """Serial diagnostic execution with three explicitly justified attempts per cell.

    The default pilot has at most 40 cells; an explicit matrix plan permits 280.

    O(C + A*N) validation for C cells, A attempts and N records per attempt.
    Scheduling and retained-ledger writes add O(C*A) metadata work (A <= 3*C).
    Retained evidence grows with attempts; working memory is bounded by one bundle.
    """
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("campaign must be a real directory")
    if not isinstance(replacement_reason, str) or len(replacement_reason) > 1024:
        raise ValueError("replacement reason must be at most 1024 characters")
    cancel = cancel if cancel is not None else Event()
    descriptor = os.open(
        directory / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
    )
    with os.fdopen(descriptor, "w") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ValueError("campaign lock must be a regular file")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan, progress, trials = _load(directory)
        return _execute_schedule(directory, plan, progress, trials, replacement_reason, cancel)


def _execute_schedule(directory, plan, progress, trials, reason, cancel):
    progress["state"] = "running"
    try:
        for cell, trial in zip(plan["schedule"]["cells"], trials, strict=True):
            if cancel.is_set():
                raise InterruptedError("campaign cancelled")
            attempt = _next_attempt(progress, cell, reason)
            if attempt is None:
                continue
            atomic_json(directory / "progress.json", progress)
            _execute(directory, trial, attempt, cancel, plan["source"])
            atomic_json(directory / "progress.json", progress)
        progress["state"] = "completed"
    except (OSError, ValueError, RuntimeError, TimeoutError, KeyboardInterrupt) as exc:
        progress["state"] = "stopped"
        try:
            atomic_json(directory / "progress.json", progress)
        except (OSError, ValueError) as persistence_error:
            exc.add_note(f"Saving the stopped campaign also failed: {persistence_error}")
        raise
    atomic_json(directory / "progress.json", progress)
    return progress
