"""One recorded diagnostic campaign from inspection through statistical and ML analysis."""

import argparse
import json
import signal
import sys
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.artifacts import atomic_json, read_json  # noqa: E402
from src.campaign import create_campaign, execute_campaign, resolve_trials  # noqa: E402
from src.hardware_probe import local_hardware  # noqa: E402
from src.hardware_smoke import run_smoke, smoke_plan  # noqa: E402
from src.telemetry import Telemetry  # noqa: E402
from src.topology_runtime import require_linux  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def plan(diagnostic_matrix: bool = False, *, transport="udp", shadow_forecast=False) -> dict:
    name = "primary.json" if diagnostic_matrix else "pilot.json"
    configuration = read_json(ROOT / "configs" / name, 65536)
    schedule, _ = resolve_trials(
        configuration,
        10,
        diagnostic_matrix=diagnostic_matrix,
        transport=transport,
        shadow_forecast=shadow_forecast,
    )
    return {
        "schema_version": 1,
        "kind": "virtual_testbed_diagnostic_matrix"
        if diagnostic_matrix
        else "virtual_testbed_diagnostic_pilot",
        "diagnostic_matrix": diagnostic_matrix,
        "configuration": configuration,
        "transport": transport,
        "shadow_forecast": shadow_forecast,
        "trials": len(schedule["cells"]),
        "setup": smoke_plan(),
        "warmup_seconds": 10,
        "analysis": ["paired_block_bootstrap", "kmeans", "pca", "tsne"],
        "eligible_for_primary": False,
        "physical_interfaces_modified": False,
    }


def run(
    directory: Path,
    authorized: bool,
    cancel: Event,
    *,
    diagnostic_matrix: bool = False,
    telemetry: Telemetry | None = None,
    transport="udp",
    shadow_forecast=False,
) -> dict:
    if not authorized:
        raise PermissionError("execution requires --authorized-isolated-host")
    require_linux()
    from analysis.policy_comparison import analyze
    from scripts.export_pilot import export

    resolved = plan(diagnostic_matrix, transport=transport, shadow_forecast=shadow_forecast)
    if cancel.is_set():
        raise InterruptedError("experiment cancelled before setup")
    directory.mkdir(mode=0o700)
    trace = telemetry if telemetry is not None else Telemetry(directory)
    report = {"state": "running", "stage": "inspection", "eligible_for_primary": False}
    atomic_json(directory / "plan.json", resolved)
    atomic_json(directory / "status.json", report)
    try:
        with trace.stage("inspection"):
            atomic_json(directory / "hardware.json", local_hardware())
        _stage(directory, report, "setup_check", cancel)
        with trace.stage("setup_check"):
            run_smoke(directory / "setup", True, cancel)
        _stage(directory, report, "campaign", cancel)
        with trace.stage("namespace_collection"):
            create_campaign(
                directory / "campaign",
                resolved["configuration"],
                10,
                diagnostic_matrix=diagnostic_matrix,
                transport=transport,
                shadow_forecast=shadow_forecast,
            )
            execute_campaign(directory / "campaign", cancel=cancel)
        _stage(directory, report, "export", cancel)
        with trace.stage("export"):
            export(directory / "campaign", directory / "export")
        _stage(directory, report, "analysis", cancel)
        with trace.stage("analysis"):
            analyze([directory / "export"], directory / "analysis")
        _stage(directory, report, "completed", cancel)
        report.update(state="completed", stage="completed")
        atomic_json(directory / "status.json", report)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, KeyboardInterrupt) as error:
        report.update(
            state="cancelled" if cancel.is_set() else "failed", error_type=type(error).__name__
        )
        try:
            atomic_json(directory / "status.json", report)
        except (OSError, ValueError) as persistence:
            error.add_note(f"experiment status could not be retained: {persistence}")
        raise
    return report


def _stage(directory, report, name, cancel):
    if cancel.is_set():
        raise InterruptedError("experiment cancelled")
    report["stage"] = name
    atomic_json(directory / "status.json", report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "run"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--authorized-isolated-host", action="store_true")
    parser.add_argument("--diagnostic-matrix", action="store_true")
    parser.add_argument("--transport", choices=("udp", "tcp"), default="udp")
    parser.add_argument("--shadow-forecast", action="store_true")
    args = parser.parse_args()
    cancel = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: cancel.set()) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        if args.action == "run" and args.output is None:
            raise ValueError("run requires a fresh --output directory")
        result = (
            plan(
                args.diagnostic_matrix,
                transport=args.transport,
                shadow_forecast=args.shadow_forecast,
            )
            if args.action == "plan"
            else run(
                args.output,
                args.authorized_isolated_host,
                cancel,
                diagnostic_matrix=args.diagnostic_matrix,
                transport=args.transport,
                shadow_forecast=args.shadow_forecast,
            )
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    except InterruptedError as error:
        print(f"Experiment cancelled: {error}", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, ImportError) as error:
        print(f"Experiment failed: {error}", file=sys.stderr)
        return 2
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
