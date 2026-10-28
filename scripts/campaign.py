"""Run or explicitly continue a small randomized Linux namespace pilot."""

import argparse
import json
import signal
import sys
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.artifacts import read_json  # noqa: E402
from src.campaign import create_campaign, execute_campaign  # noqa: E402
from src.topology_runtime import require_linux  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--warmup-seconds", type=int, default=10)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--replacement-reason", default="")
    parser.add_argument("--authorized-isolated-host", action="store_true")
    args = parser.parse_args()
    cancel = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: cancel.set()) for sig in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        if not args.authorized_isolated_host:
            raise PermissionError("namespace pilot requires --authorized-isolated-host")
        require_linux()
        if args.resume:
            if args.config is not None:
                raise ValueError("resume uses the retained plan; omit --config")
        else:
            if args.config is None or args.replacement_reason:
                raise ValueError("a new campaign needs --config and no replacement reason")
            create_campaign(args.output, read_json(args.config, 65536), args.warmup_seconds)
        result = execute_campaign(
            args.output, replacement_reason=args.replacement_reason, cancel=cancel
        )
        print(json.dumps({"state": result["state"], "attempts": len(result["attempts"])}))
        return 0
    except InterruptedError as exc:
        print(f"Pilot stopped: {exc}", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Pilot failed: {exc}", file=sys.stderr)
        return 2
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
