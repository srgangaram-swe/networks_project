"""Use the same queue plan across three explicitly configured Linux roles."""

from pathlib import Path

from src.artifacts import parse_json
from src.physical_commands import split_command
from src.physical_profile import check_inspections, validate_profile, worker_command
from src.processes import run_command
from src.queue_policy import check_queue_kinds, policy_commands
from src.topology import (
    CLIENT_ADDRESS,
    ROLES,
    SERVER_ADDRESS,
    Topology,
    configuration_commands,
    inspection_commands,
)


class PhysicalBackend:
    def __init__(self, profile: dict, token: str, policy: str, *, transport="udp"):
        self.profile = validate_profile(profile)
        self.topology = Topology(token)
        self.policy = policy
        self.transport = transport
        self.prepared: list[str] = []
        self.client_address = CLIENT_ADDRESS
        self.server_address = SERVER_ADDRESS
        # The trial coordinator runs on the client so every RTT deadline uses its clock.
        self.profile = {
            **profile,
            "roles": {
                **profile["roles"],
                "client": {**profile["roles"]["client"], "host": "local"},
            },
        }

    def setup(self):
        inspections = []
        for role in ROLES:
            result = run_command(
                worker_command(self.profile, role, "inspect", self.topology.token), timeout=30
            )
            inspections.append(parse_json(result.stdout))
        check_inspections(inspections)
        for role in ROLES:
            run_command(
                worker_command(self.profile, role, "prepare", self.topology.token), timeout=45
            )
            self.prepared.append(role)
        for command in configuration_commands(self.topology) + policy_commands(
            self.topology, self.policy, transport=self.transport
        ):
            role, args = split_command(command, self.topology)
            run_command(self.command(role, args), timeout=30)

    def command(self, role: str, args: tuple[str, ...]) -> tuple[str, ...]:
        if role not in self.prepared:
            raise RuntimeError("physical role has not been prepared")
        if len(args) > 1 and Path(args[1]).name in {"foreground.py", "tcp_observer.py"}:
            root = Path(self.profile["roles"][role]["repository"])
            args = (
                str(root / ".venv/bin/python"),
                str(root / "scripts" / Path(args[1]).name),
                *args[2:],
            )
        return worker_command(self.profile, role, "exec", self.topology.token, args=list(args))

    def snapshot(self):
        snapshots = {}
        for name, command in inspection_commands(self.topology).items():
            role, args = split_command(command, self.topology)
            snapshots[name] = parse_json(run_command(self.command(role, args), timeout=30).stdout)
        check_queue_kinds(snapshots["router_queues"], self.policy)
        return {
            "kind": "physical_testbed",
            "attachment_checked": True,
            "calibrated": False,
            "snapshots": snapshots,
        }

    def close(self):
        errors = []
        for role in self.prepared[::-1]:
            try:
                run_command(
                    worker_command(self.profile, role, "cleanup", self.topology.token), timeout=45
                )
            except (OSError, ValueError, RuntimeError) as error:
                errors.append(f"{role}: {error}")
        if errors:
            raise RuntimeError("physical cleanup incomplete; retain journals: " + "; ".join(errors))
        self.prepared.clear()
