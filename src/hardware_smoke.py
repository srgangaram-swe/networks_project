"""Run a short unloaded namespace check on a dedicated Linux mini PC."""

from pathlib import Path
from threading import Event

from src.artifacts import atomic_json
from src.bundle_validation import validate_bundle
from src.experiment_config import POLICIES
from src.testbed_contract import verify_contract
from src.topology_runtime import require_linux
from src.trial import TrialConfig, run_trial


def smoke_plan() -> dict:
    """Four fixed trials; no physical interfaces, bulk flow, or network mutation."""
    return {
        "schema_version": 1,
        "contract": verify_contract(),
        "mode": "namespace",
        "network_changes": False,
        "host_interfaces_modified": False,
        "physical_nic_test": False,
        "eligible_for_primary": False,
        "policies": sorted(POLICIES),
        "warmup_seconds": 0,
        "measurement_seconds_per_policy": 2,
        "drain_seconds_per_policy": 2,
        "flows": 0,
        "aggregate_bps": 0,
        "purpose": "unloaded_setup_and_cleanup_only",
    }


def run_smoke(directory: Path, authorized: bool, cancel: Event) -> dict:
    """Retain four bounded trials or the first failure; never retry or overwrite.

    Workload memory is bounded by TrialConfig. The summary has at most four
    entries. Existing trial ownership handles namespace rollback and process
    cleanup. An unsuccessful attempt keeps its manifest and output directory.
    """
    if not authorized:
        raise PermissionError("smoke run requires --authorized-isolated-host")
    require_linux()
    plan = smoke_plan()
    if cancel.is_set():
        raise InterruptedError("smoke run cancelled before setup")
    directory.mkdir(mode=0o700)
    atomic_json(directory / "plan.json", plan)
    summary = {"state": "running", "completed": [], "eligible_for_primary": False}
    atomic_json(directory / "summary.json", summary)
    try:
        for policy in plan["policies"]:
            if cancel.is_set():
                raise InterruptedError("smoke run cancelled")
            trial = directory / policy
            run_trial(
                trial,
                TrialConfig(
                    mode="namespace",
                    policy=policy,
                    flows=0,
                    aggregate_bps=0,
                    measurement_seconds=2,
                    warmup_seconds=0,
                ),
                cancel,
            )
            result = validate_bundle(trial)
            summary["completed"].append(
                {"policy": policy, "integrity_valid": result["integrity_valid"]}
            )
            atomic_json(directory / "summary.json", summary)
        summary["state"] = "completed"
        atomic_json(directory / "summary.json", summary)
    except (OSError, ValueError, RuntimeError, TimeoutError, KeyboardInterrupt) as exc:
        summary["state"] = (
            "cancelled" if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else "failed"
        )
        summary["error_type"] = type(exc).__name__
        try:
            atomic_json(directory / "summary.json", summary)
        except (OSError, ValueError) as persistence:
            exc.add_note(f"smoke summary could not be saved: {persistence}")
        raise
    return summary
