"""Run one bounded loopback diagnostic or an authorized Linux namespace pilot."""

import argparse
import json
import signal
import sys
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.trial import TrialConfig, run_trial  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("loopback", "namespace"), default="loopback")
    parser.add_argument("--policy", default="none")
    parser.add_argument("--seconds", type=int, default=2)
    parser.add_argument("--warmup-seconds", type=int, default=0)
    parser.add_argument("--flows", type=int, choices=(0, 1, 8), default=1)
    parser.add_argument("--aggregate-bps", type=int, default=8_000_000)
    parser.add_argument("--foreground-port", type=int, default=42000)
    parser.add_argument("--bulk-port", type=int, default=5201)
    parser.add_argument("--authorized-isolated-host", action="store_true")
    args = parser.parse_args()
    cancel = Event()
    previous = {
        sig: signal.signal(sig, lambda *_args: cancel.set())
        for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        if args.mode == "namespace" and not args.authorized_isolated_host:
            raise PermissionError("namespace mode requires --authorized-isolated-host")
        config = TrialConfig(
            args.mode,
            args.policy,
            args.seconds,
            args.warmup_seconds,
            args.flows,
            args.aggregate_bps,
            args.foreground_port,
            args.bulk_port,
        )
        result = run_trial(args.output, config, cancel)
        print(
            json.dumps(
                {
                    "state": result["state"],
                    "run_id": result["run_id"],
                    "eligible_for_primary": False,
                }
            )
        )
        return 0
    except InterruptedError as exc:
        print(f"Trial cancelled: {exc}", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Trial failed: {exc}", file=sys.stderr)
        return 2
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
