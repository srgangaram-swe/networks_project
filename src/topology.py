"""Pure command planning for three isolated Linux network namespaces."""

import re
from dataclasses import dataclass

CLIENT_ADDRESS = "10.203.0.2"
SERVER_ADDRESS = "10.203.0.6"
ROLES = ("client", "router", "server")


@dataclass(frozen=True)
class Topology:
    token: str

    def __post_init__(self) -> None:
        if not isinstance(self.token, str) or not re.fullmatch(r"[a-f0-9]{12}", self.token):
            raise ValueError("topology token must contain exactly 12 lowercase hex digits")

    def namespace(self, role: str) -> str:
        if role not in ROLES:
            raise ValueError("unknown topology role")
        return f"np-{self.token}-{role}"

    def command(self, role: str, *args: str) -> tuple[str, ...]:
        return ("ip", "netns", "exec", self.namespace(role), *args)

    def link(self, role: str, *args: str) -> tuple[str, ...]:
        return ("ip", "-n", self.namespace(role), *args)


def _endpoint_commands(topology: Topology, role: str, address: str, gateway: str) -> list:
    return [
        topology.link(role, "addr", "add", f"{address}/30", "dev", "eth0"),
        topology.link(role, "route", "add", "default", "via", gateway),
        topology.command(role, "sysctl", "-qw", "net.ipv4.tcp_ecn=0"),
        topology.command(role, "sysctl", "-qw", "net.ipv4.tcp_congestion_control=cubic"),
        topology.link(role, "link", "add", "ifb0", "type", "ifb"),
        topology.link(role, "link", "set", "ifb0", "up"),
        topology.command(role, "tc", "qdisc", "add", "dev", "eth0", "handle", "ffff:", "ingress"),
        topology.command(
            role,
            "tc",
            "filter",
            "add",
            "dev",
            "eth0",
            "parent",
            "ffff:",
            "protocol",
            "all",
            "pref",
            "1",
            "matchall",
            "action",
            "mirred",
            "egress",
            "redirect",
            "dev",
            "ifb0",
        ),
        topology.command(
            role,
            "tc",
            "qdisc",
            "add",
            "dev",
            "ifb0",
            "root",
            "handle",
            "10:",
            "netem",
            "limit",
            "10000",
            "delay",
            "10ms",
        ),
    ]


def setup_commands(topology: Topology) -> list[tuple[str, ...]]:
    """Return a fixed-size plan; all routes, devices, and sysctls live in namespaces."""
    router = topology.namespace("router")
    commands = [
        topology.link(
            "client",
            "link",
            "add",
            "eth0",
            "type",
            "veth",
            "peer",
            "name",
            "to-client",
            "netns",
            router,
        ),
        topology.link(
            "server",
            "link",
            "add",
            "eth0",
            "type",
            "veth",
            "peer",
            "name",
            "to-server",
            "netns",
            router,
        ),
    ]
    for role, devices in (
        ("client", ("eth0",)),
        ("router", ("to-client", "to-server")),
        ("server", ("eth0",)),
    ):
        commands.append(topology.link(role, "link", "set", "lo", "up"))
        for device in devices:
            commands.extend(
                [
                    topology.link(role, "link", "set", device, "mtu", "1500", "up"),
                    topology.command(
                        role,
                        "ethtool",
                        "-K",
                        device,
                        "tso",
                        "off",
                        "gso",
                        "off",
                        "gro",
                        "off",
                        "lro",
                        "off",
                    ),
                ]
            )
    commands.extend(
        [
            topology.link("router", "addr", "add", "10.203.0.1/30", "dev", "to-client"),
            topology.link("router", "addr", "add", "10.203.0.5/30", "dev", "to-server"),
            topology.command("router", "sysctl", "-qw", "net.ipv4.ip_forward=1"),
        ]
    )
    commands.extend(_endpoint_commands(topology, "client", CLIENT_ADDRESS, "10.203.0.1"))
    commands.extend(_endpoint_commands(topology, "server", SERVER_ADDRESS, "10.203.0.5"))
    return commands


def inspection_commands(topology: Topology) -> dict[str, tuple[str, ...]]:
    commands = {}
    for role in ROLES:
        commands[f"{role}_links"] = topology.link(role, "-j", "-s", "link", "show")
        commands[f"{role}_routes"] = topology.link(role, "-j", "route", "show")
        commands[f"{role}_queues"] = topology.command(role, "tc", "-j", "-s", "qdisc", "show")
    commands["classification"] = topology.command(
        "router", "tc", "-j", "-s", "filter", "show", "dev", "to-server", "ingress"
    )
    return commands
