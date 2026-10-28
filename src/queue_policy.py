"""Fixed, reviewable queue profiles for the owned namespace topology."""

from src.experiment_config import POLICIES, bounded_integer
from src.topology import CLIENT_ADDRESS, SERVER_ADDRESS, Topology


def _sanitize(topology: Topology) -> list[tuple[str, ...]]:
    commands = []
    for interface in ("to-client", "to-server"):
        commands.append(
            topology.command("router", "tc", "qdisc", "add", "dev", interface, "clsact")
        )
        # ECN is disabled for this protocol. Clear the full DS field and repair
        # the IPv4 checksum before any classification based on our own rules.
        commands.append(
            topology.command(
                "router",
                "tc",
                "filter",
                "add",
                "dev",
                interface,
                "ingress",
                "protocol",
                "ip",
                "pref",
                "1",
                "matchall",
                "action",
                "pedit",
                "ex",
                "munge",
                "ip",
                "dsfield",
                "set",
                "0",
                "pipe",
                "action",
                "csum",
                "ip4h",
                "pipe",
                "action",
                "skbedit",
                "priority",
                "0",
                "pass",
            )
        )
    return commands


def _bounded_filters(topology: Topology) -> list[tuple[str, ...]]:
    prefix = ("tc", "filter", "add", "dev", "to-client", "parent", "1:", "protocol", "ip")
    return [
        topology.command(
            "router",
            *prefix,
            "pref",
            "1",
            "flower",
            "src_ip",
            SERVER_ADDRESS,
            "dst_ip",
            CLIENT_ADDRESS,
            "ip_proto",
            "udp",
            "src_port",
            "42000",
            "dst_port",
            "42001",
            "action",
            "police",
            "rate",
            "5mbit",
            "burst",
            "16384",
            "conform-exceed",
            "continue/pipe",
            "action",
            "pedit",
            "ex",
            "munge",
            "ip",
            "dsfield",
            "set",
            "184",
            "pipe",
            "action",
            "csum",
            "ip4h",
            "pipe",
            "action",
            "skbedit",
            "priority",
            "1:3",
            "pass",
        ),
        topology.command(
            "router",
            *prefix,
            "pref",
            "10",
            "matchall",
            "action",
            "skbedit",
            "priority",
            "1:2",
            "pass",
        ),
    ]


def policy_commands(topology: Topology, policy: str) -> list[tuple[str, ...]]:
    """Plan O(1) commands at the fixed 100 Mb/s candidate protocol settings.

    Install once into a fresh topology. Reset means replacing that whole owned
    topology, which prevents stale filters or queue state between treatments.
    """
    if policy not in POLICIES:
        raise ValueError("unsupported queue policy")
    commands = _sanitize(topology)
    prefix = ("tc", "qdisc", "add", "dev", "to-client")
    if policy in {"fifo", "fq_codel"}:
        commands.extend(
            [
                topology.command("router", *prefix, "root", "handle", "1:", "htb", "default", "10"),
                topology.command(
                    "router",
                    "tc",
                    "class",
                    "add",
                    "dev",
                    "to-client",
                    "parent",
                    "1:",
                    "classid",
                    "1:10",
                    "htb",
                    "rate",
                    "100mbit",
                    "ceil",
                    "100mbit",
                    "burst",
                    "16384",
                    "cburst",
                    "16384",
                    "quantum",
                    "1514",
                ),
            ]
        )
        leaf = (
            ("bfifo", "limit", "250000")
            if policy == "fifo"
            else (
                "fq_codel",
                "limit",
                "1024",
                "flows",
                "1024",
                "quantum",
                "1514",
                "target",
                "5ms",
                "interval",
                "100ms",
                "noecn",
                "memory_limit",
                "4194304",
            )
        )
        commands.append(
            topology.command("router", *prefix, "parent", "1:10", "handle", "10:", *leaf)
        )
    else:
        mode = "diffserv3" if policy == "cake_bounded" else "besteffort"
        commands.append(
            topology.command(
                "router",
                *prefix,
                "root",
                "handle",
                "1:",
                "cake",
                "bandwidth",
                "100mbit",
                mode,
                "flows",
                "nonat",
                "raw",
                "rtt",
                "20ms",
                "memlimit",
                "4194304",
                "no-ack-filter",
            )
        )
        if policy == "cake_bounded":
            commands.extend(_bounded_filters(topology))
    return commands


def check_queue_kinds(snapshot: object, policy: str) -> None:
    """Check attachment only; counters and calibrated rates still require traffic."""
    if policy not in POLICIES or not isinstance(snapshot, list) or len(snapshot) > 32:
        raise ValueError("invalid queue snapshot or policy")
    if any(not isinstance(row, dict) for row in snapshot):
        raise ValueError("queue rows must be objects")
    rows = [row for row in snapshot if row.get("dev") == "to-client"]
    root = "htb" if policy in {"fifo", "fq_codel"} else "cake"
    if not any(row.get("kind") == root and row.get("handle") == "1:" for row in rows):
        raise ValueError("selected root queue is not attached")
    if policy in {"fifo", "fq_codel"}:
        leaf = "bfifo" if policy == "fifo" else "fq_codel"
        if not any(row.get("kind") == leaf and row.get("parent") == "1:10" for row in rows):
            raise ValueError("selected leaf queue is not attached")


def counter_delta(before: dict, after: dict) -> dict[str, int]:
    if any(before.get(key) != after.get(key) for key in ("dev", "kind", "handle")):
        raise ValueError("queue identity changed between counter snapshots")
    result = {}
    for key in ("bytes", "packets", "drops"):
        start = bounded_integer(before.get(key), key, 0, 2**64 - 1)
        end = bounded_integer(after.get(key), key, start, 2**64 - 1)
        result[key] = end - start
    return result
