"""Keep Linux mutations separate from portable trial orchestration."""

import uuid
from pathlib import Path

from src.artifacts import parse_json
from src.processes import run_command
from src.queue_policy import check_queue_kinds, policy_commands
from src.topology import CLIENT_ADDRESS, SERVER_ADDRESS, Topology, inspection_commands
from src.topology_runtime import OwnedTopology, require_linux


class Backend:
    def __init__(self, mode: str, policy: str, directory: Path):
        if mode not in {"loopback", "namespace"}:
            raise ValueError("unsupported backend")
        if mode == "loopback" and policy != "none":
            raise ValueError("loopback cannot represent a Linux queue policy")
        self.mode = mode
        self.policy = policy
        self.directory = directory
        self.lease: OwnedTopology | None = None
        self.topology = Topology(uuid.uuid4().hex[:12])
        self.client_address = "127.0.0.1" if mode == "loopback" else CLIENT_ADDRESS
        self.server_address = "127.0.0.1" if mode == "loopback" else SERVER_ADDRESS

    def setup(self) -> None:
        if self.mode == "loopback":
            return
        require_linux()
        # Check the policy before creating any resources.
        commands = policy_commands(self.topology, self.policy)
        self.lease = OwnedTopology.create(self.directory / "topology", self.topology)
        self.lease.setup()
        for command in commands:
            run_command(command)

    def command(self, role: str, args: tuple[str, ...]) -> tuple[str, ...]:
        if self.mode == "loopback":
            return args
        if self.lease is None:
            raise RuntimeError("namespace backend has not been set up")
        self.lease.verify()
        return self.topology.command(role, *args)

    def snapshot(self) -> dict:
        if self.mode == "loopback":
            return {"kind": "loopback", "network_changes": False, "queue_verified": False}
        if self.lease is None:
            raise RuntimeError("namespace backend has not been set up")
        self.lease.verify()
        result = {
            name: parse_json(run_command(command).stdout)
            for name, command in inspection_commands(self.topology).items()
        }
        check_queue_kinds(result["router_queues"], self.policy)
        return {
            "kind": "virtual_testbed",
            "attachment_checked": True,
            "calibrated": False,
            "snapshots": result,
        }

    def close(self) -> None:
        if self.lease is not None:
            try:
                self.lease.cleanup()
            finally:
                self.lease.__exit__()
                self.lease = None
