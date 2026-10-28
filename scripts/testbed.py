"""Plan, apply, inspect, or clean up a project-owned Linux namespace topology."""

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.artifacts import parse_json  # noqa: E402
from src.processes import run_command  # noqa: E402
from src.queue_policy import policy_commands  # noqa: E402
from src.topology import ROLES, Topology, inspection_commands, setup_commands  # noqa: E402
from src.topology_runtime import OwnedTopology, require_linux  # noqa: E402


def operate(args) -> dict:
    if args.action == "plan":
        topology = Topology(args.token or uuid.uuid4().hex[:12])
        commands = [("ip", "netns", "add", topology.namespace(role)) for role in ROLES]
        commands += setup_commands(topology) + policy_commands(topology, args.policy)
        return {
            "network_changes": False,
            "token": topology.token,
            "policy": args.policy,
            "commands": commands,
        }
    if not args.authorized_isolated_host or args.state is None:
        raise PermissionError("provide --state and --authorized-isolated-host")
    require_linux()
    if args.action == "setup":
        topology = Topology(args.token or uuid.uuid4().hex[:12])
        commands = policy_commands(topology, args.policy)
        with OwnedTopology.create(args.state, topology) as lease:
            try:
                lease.setup()
                for command in commands:
                    run_command(command)
            except BaseException as primary:
                try:
                    lease.cleanup()
                except (OSError, RuntimeError) as cleanup:
                    primary.add_note(f"cleanup also failed: {cleanup}")
                raise
        return {"state": "created", "token": topology.token, "policy": args.policy}
    with OwnedTopology(args.state) as lease:
        if args.action == "cleanup":
            lease.cleanup()
            return {"state": "cleaned"}
        lease.verify()
        return {
            name: parse_json(run_command(command).stdout)
            for name, command in inspection_commands(lease.topology).items()
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "setup", "inspect", "cleanup"))
    parser.add_argument("--state", type=Path)
    parser.add_argument("--policy", default="fifo")
    parser.add_argument("--token")
    parser.add_argument("--authorized-isolated-host", action="store_true")
    try:
        print(json.dumps(operate(parser.parse_args()), indent=2))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Testbed operation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
