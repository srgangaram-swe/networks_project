"""Plan or run four unloaded checks using only owned Linux namespaces."""

import argparse
import json
import signal
import sys
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.hardware_smoke import run_smoke, smoke_plan  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "run"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--authorized-isolated-host", action="store_true")
    args = parser.parse_args()
    cancel = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: cancel.set()) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        if args.action == "plan":
            report = smoke_plan()
        else:
            if args.output is None:
                raise ValueError("run requires an unused --output directory")
            report = run_smoke(args.output, args.authorized_isolated_host, cancel)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except InterruptedError as exc:
        print(f"Smoke check cancelled: {exc}", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Smoke check failed: {exc}", file=sys.stderr)
        return 2
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
