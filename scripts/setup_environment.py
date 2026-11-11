"""Create or check the project's pinned virtual environment on macOS or Linux."""

import argparse
import json
import signal
import sys
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.environment import ROOT, environment_plan, setup_environment  # noqa: E402
from src.processes import run_command  # noqa: E402


def _runner(cancel):
    def run(*args, **kwargs):
        if cancel.is_set():
            raise InterruptedError("environment setup cancelled")
        result = run_command(*args, stop=cancel, **kwargs)
        if cancel.is_set():
            raise InterruptedError("environment setup cancelled")
        return result

    return run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", type=Path, default=ROOT / ".venv")
    parser.add_argument("--profile", choices=("development", "analysis"), default="development")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    cancel = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: cancel.set())
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
    }
    try:
        result = (
            environment_plan(args.venv, args.profile)
            if args.plan
            else setup_environment(args.venv, args.profile, run=_runner(cancel))
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    except InterruptedError as error:
        print(f"Environment setup cancelled: {error}", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Environment setup failed: {error}", file=sys.stderr)
        return 2
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
