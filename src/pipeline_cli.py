"""Command-line options for one recorded pipeline run."""

import argparse
import json
import os
import platform
import signal
import sys
from pathlib import Path
from threading import Event

from src.artifacts import read_json
from src.pipeline import configure_logging, plan, run
from src.simulation import ROOT, default_workers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology", choices=("local", "namespace", "physical"), required=True)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--transport", choices=("udp", "tcp"), default="udp")
    parser.add_argument("--shadow-forecast", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--workers", type=int, default=default_workers())
    parser.add_argument("--simulation-multiplier", type=int, default=3)
    parser.add_argument("--seed", type=int, default=561)
    parser.add_argument("--diagnostic-matrix", action="store_true")
    parser.add_argument("--authorized-isolated-host", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    cancel = Event()
    previous = {
        s: signal.signal(s, lambda *_: cancel.set()) for s in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        profile = read_json(args.profile, 16384) if args.profile else None
        if args.plan:
            result = plan(
                args.topology,
                args.simulation_multiplier,
                args.seed,
                profile,
                args.diagnostic_matrix,
                transport=args.transport,
                shadow_forecast=args.shadow_forecast,
            )
        else:
            if args.output is None:
                raise ValueError("execution requires a fresh --output directory")
            _namespace_privilege(args)
            result = run(
                args.output,
                args.topology,
                workers=args.workers,
                multiplier=args.simulation_multiplier,
                seed=args.seed,
                profile=profile,
                authorized=args.authorized_isolated_host,
                diagnostic_matrix=args.diagnostic_matrix,
                cancel=cancel,
                transport=args.transport,
                shadow_forecast=args.shadow_forecast,
            )
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (InterruptedError, KeyboardInterrupt) as error:
        print(f"Pipeline cancelled: {error}", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, ImportError) as error:
        print(f"Pipeline failed: {error}", file=sys.stderr)
        return 2
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _namespace_privilege(args):
    if args.topology != "namespace":
        return
    if not args.authorized_isolated_host or platform.system() != "Linux":
        raise PermissionError("namespace execution needs an authorized, isolated Linux host")
    if os.geteuid() != 0:
        os.execvp(
            "sudo", ("sudo", "-n", sys.executable, str(ROOT / "scripts/pipeline.py"), *sys.argv[1:])
        )
