"""Bounded RPC endpoints used by the trial runner on each supported host."""

import argparse
import json
import signal
import sys
from pathlib import Path
from threading import Event

from src.artifacts import atomic_json
from src.basic_rpc_protocol.rpc_connector import run_server
from src.basic_rpc_protocol.rpc_server import RpcServer
from src.basic_rpc_protocol.rpc_workload import RpcWorkloadConfig, run_rpc_workload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("client", "server"))
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--peer", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5300)
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-isolated", action="store_true")
    args = parser.parse_args()
    stop = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stop.set())
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    }
    try:
        result = _execute(args, stop)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0 if result["status"] in {"completed", "cancelled"} else 2
    except (OSError, ValueError, RuntimeError) as error:
        print(f"RPC endpoint failed: {error}", file=sys.stderr)
        return 2
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _execute(args, stop):
    if args.action == "server":
        return run_server(
            RpcServer(lambda payload: payload),
            (args.bind, args.port),
            args.peer,
            duration_ms=args.seconds * 1000,
            allow_isolated=args.allow_isolated,
            stop=stop,
            ready=lambda address: print(json.dumps({"ready": list(address)}), flush=True),
        )
    if args.output is None or args.output.exists():
        raise ValueError("RPC client requires a fresh --output file")
    config = RpcWorkloadConfig(
        bind=(args.bind, 0),
        peer=(args.peer, args.port),
        measurement_seconds=args.seconds,
        allow_isolated=args.allow_isolated,
    )
    result = run_rpc_workload(config, stop=stop)
    atomic_json(args.output, result)
    return {"status": result["status"], "admitted_calls": result["admitted_calls"]}
