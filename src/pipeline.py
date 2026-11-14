"""Topology selection and automatic collection, export, analysis, and findings."""

import logging
from pathlib import Path
from threading import Event

from src.artifacts import atomic_json, read_json
from src.experiment_config import bounded_integer
from src.physical_campaign import collect_physical, physical_plan, preflight
from src.physical_profile import validate_profile
from src.run_bundle import source_identity
from src.simulation import ROOT, collect_simulation, simulation_plan
from src.table_export import export_run_tables
from src.telemetry import Telemetry


def plan(
    topology: str,
    multiplier=3,
    seed=561,
    profile=None,
    diagnostic_matrix=False,
    *,
    transport="udp",
    shadow_forecast=False,
):
    if topology == "local":
        if shadow_forecast:
            raise ValueError("live shadow forecasts require namespace or physical traffic")
        if diagnostic_matrix:
            raise ValueError("local mode uses its explicit simulation multiplier")
        return simulation_plan(multiplier, seed, transport=transport)
    if topology == "namespace":
        from scripts.nucbox_experiment import plan as namespace_plan

        return namespace_plan(
            diagnostic_matrix, transport=transport, shadow_forecast=shadow_forecast
        )
    if topology != "physical" or profile is None:
        raise ValueError("physical mode requires an explicit private --profile")
    validate_profile(profile)
    raw = read_json(ROOT / "configs" / ("primary.json" if diagnostic_matrix else "pilot.json"))
    return physical_plan(
        raw, source_identity(ROOT), transport=transport, shadow_forecast=shadow_forecast
    )


def run(
    output: Path,
    topology: str,
    *,
    workers=4,
    multiplier=3,
    seed=561,
    profile=None,
    authorized=False,
    diagnostic_matrix=False,
    cancel=None,
    transport="udp",
    shadow_forecast=False,
):
    bounded_integer(workers, "workers", 1, 8)
    resolved = plan(
        topology,
        multiplier,
        seed,
        profile,
        diagnostic_matrix,
        transport=transport,
        shadow_forecast=shadow_forecast,
    )
    if topology != "local" and not authorized:
        raise PermissionError("testbed collection requires --authorized-isolated-host")
    cancel = cancel if cancel is not None else Event()
    if cancel.is_set():
        raise InterruptedError("pipeline cancelled before creating output")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.mkdir(mode=0o700)
    trace = Telemetry(output)
    status = {"state": "running", "topology": topology, "eligible_for_primary": False}
    atomic_json(output / "status.json", status)
    atomic_json(output / "plan.json", resolved)
    try:
        _execute(
            output,
            topology,
            resolved,
            profile,
            workers,
            authorized,
            diagnostic_matrix,
            cancel,
            trace,
        )
        if cancel.is_set():
            raise InterruptedError("pipeline cancelled after its last completed stage")
        status["state"] = "completed"
        trace.event("pipeline_completed", topology=topology)
        atomic_json(output / "status.json", status)
    except BaseException as error:
        status.update(
            state="cancelled"
            if isinstance(error, (InterruptedError, KeyboardInterrupt))
            else "failed",
            error_type=type(error).__name__,
            error=str(error)[:1024],
        )
        try:
            atomic_json(output / "status.json", status)
            trace.event("pipeline_failed", **status)
        except (OSError, ValueError) as persistence:
            error.add_note(f"retaining pipeline failure also failed: {persistence}")
        raise
    return status


def _execute(output, topology, resolved, profile, workers, authorized, matrix, cancel, trace):
    if topology == "namespace":
        from scripts.nucbox_experiment import run as namespace_run

        namespace_run(
            output / "namespace",
            authorized,
            cancel,
            diagnostic_matrix=matrix,
            telemetry=trace,
            transport=resolved["transport"],
            shadow_forecast=resolved["shadow_forecast"],
        )
        return
    if topology == "physical":
        with trace.stage("physical_preflight"):
            identities = preflight(profile)
            resolved["source"] = identities["client"]
            atomic_json(output / "host-sources.json", identities)
            atomic_json(output / "plan.json", resolved)
        with trace.stage("physical_collection"):
            trials = collect_physical(output / "collection", resolved, profile, cancel, trace.event)
    else:
        with trace.stage("simulation"):
            trials = collect_simulation(output / "collection", resolved, workers, cancel)
        atomic_json(
            output / "worker-timings.json",
            {
                "workers": workers,
                "trials": trials,
                "worker_cpu_seconds": sum(t["process_cpu_seconds"] for t in trials),
            },
        )
    if cancel.is_set():
        raise InterruptedError("pipeline cancelled before export")
    with trace.stage("export"):
        export_run_tables(output / "export", output / "collection", resolved, trials)
    from analysis.policy_comparison import analyze

    with trace.stage("analysis"):
        analyze([output / "export"], output / "analysis", allow_simulated=topology == "local")


def configure_logging(verbose=False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
