"""Translate the shared topology plan into per-host namespace operations."""

from src.queue_policy import policy_commands
from src.topology import ROLES, Topology, configuration_commands, inspection_commands


def split_command(command: tuple[str, ...], topology: Topology) -> tuple[str, tuple[str, ...]]:
    names = {topology.namespace(role): role for role in ROLES}
    if command[:2] == ("ip", "-n"):
        return names[command[2]], ("ip", *command[3:])
    if command[:3] == ("ip", "netns", "exec"):
        return names[command[3]], command[4:]
    raise ValueError("command is outside the shared namespace plan")


def allowed_kernel_commands(role: str, token: str) -> set[tuple[str, ...]]:
    topology = Topology(token)
    commands = configuration_commands(topology) + list(inspection_commands(topology).values())
    for policy in ("fifo", "fq_codel", "cake_best_effort", "cake_bounded"):
        commands.extend(policy_commands(topology, policy))
        commands.extend(policy_commands(topology, policy, transport="tcp"))
    return {
        args
        for command in commands
        for found, args in [split_command(command, topology)]
        if found == role
    }
