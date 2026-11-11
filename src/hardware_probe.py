"""Read bounded Linux readiness evidence without configuring devices or modules."""

import platform
import re
import shutil
from itertools import islice
from pathlib import Path

from src.artifacts import parse_json
from src.processes import CommandError, run_command
from src.testbed_inventory import TOOLS

MAX_INTERFACES = 32
MODULES = ("sch_htb", "sch_fifo", "sch_fq_codel", "sch_cake", "sch_netem", "ifb")
VERSION_PATTERNS = {
    "ip": rb"iproute2[-, ]+([0-9][0-9A-Za-z.+~-]{0,63})",
    "tc": rb"iproute2[-, ]+([0-9][0-9A-Za-z.+~-]{0,63})",
    "iperf3": rb"iperf ([0-9][0-9A-Za-z.+~-]{0,63})",
    "tcpdump": rb"tcpdump version ([0-9][0-9A-Za-z.+~-]{0,63})",
    "ethtool": rb"ethtool version ([0-9][0-9A-Za-z.+~-]{0,63})",
}


def _probe(args: tuple[str, ...], find, run) -> tuple[str, bytes]:
    executable = find(args[0])
    if executable is None:
        return "missing", b""
    try:
        result = run((executable, *args[1:]), timeout=3, limit=16384, check=False)
    except (CommandError, OSError):
        # Never include banners or exception text that may expose local paths.
        return "probe_failed", b""
    if result.returncode:
        return "command_failed", b""
    return "available", result.stdout + result.stderr


def tool_versions(find, run) -> list[dict]:
    rows = []
    for tool, flag in TOOLS:
        status, output = _probe((tool, flag), find, run)
        version = re.search(VERSION_PATTERNS[tool], output)
        rows.append(
            {
                "tool": tool,
                "status": status,
                "version": version[1].decode("ascii") if version else None,
            }
        )
    return rows


def _default_links(find, run) -> tuple[set[str], bool]:
    protected = set()
    for family in ("-4", "-6"):
        status, output = _probe(("ip", family, "-j", "route", "show", "default"), find, run)
        if status != "available":
            return set(), False
        try:
            routes = parse_json(output)
            if not isinstance(routes, list) or len(routes) > 64:
                return set(), False
            for route in routes:
                if not isinstance(route, dict) or not isinstance(route.get("dev"), str):
                    return set(), False
                protected.add(route["dev"])
        except ValueError:
            return set(), False
    return protected, True


def _attribute(path: Path) -> str | None:
    try:
        with path.open("rb") as stream:
            raw = stream.read(257)
        if len(raw) > 256:
            return None
        return raw.decode("ascii").strip()
    except (OSError, UnicodeError):
        return None


def _number(path: Path, minimum: int, maximum: int) -> int | None:
    value = _attribute(path)
    if value is None or not re.fullmatch(r"[0-9]{1,9}", value):
        return None
    number = int(value)
    return number if minimum <= number <= maximum else None


def _driver(path: Path) -> str | None:
    try:
        name = path.resolve(strict=True).name
    except (OSError, RuntimeError):
        return None
    return name if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name) else None


def interface_inventory(root: Path, protected: set[str], routes_known: bool) -> list[dict]:
    """O(N) reads, at most 32 interfaces and 256 bytes per attribute.

    Interface names remain local in the report. MACs, addresses, serial numbers,
    and sysfs paths are never copied. An unprotected link is not authorized.
    """
    entries = list(islice(root.iterdir(), MAX_INTERFACES + 1))
    if len(entries) > MAX_INTERFACES:
        raise ValueError("interface inventory exceeds the 32-interface limit")
    rows = []
    for entry in sorted(entries):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}", entry.name):
            raise ValueError("interface name is outside the supported format")
        if not (entry / "device").exists():
            continue
        rows.append(
            {
                "interface": entry.name,
                "driver": _driver(entry / "device/driver"),
                "carrier": _number(entry / "carrier", 0, 1),
                "speed_mbps": _number(entry / "speed", 1, 1_000_000),
                "mtu": _number(entry / "mtu", 68, 65535),
                "default_route": entry.name in protected if routes_known else None,
                "authorized_for_changes": False,
            }
        )
    return rows


def inspect_hardware(
    system: str,
    *,
    net_root: Path = Path("/sys/class/net"),
    find=shutil.which,
    run=run_command,
) -> dict:
    """Collect inspection evidence; module discovery is not attachment evidence."""
    report = {
        "schema_version": 1,
        "platform": system,
        "status": "unsupported_platform",
        "network_changes": False,
        "ready_for_experiment": False,
        "tools": [],
        "modules": [],
        "interfaces": [],
        "default_routes_observed": False,
    }
    if system != "Linux":
        return report
    report["status"] = "inspection_only"
    report["kernel"] = platform.release()[:128]
    report["architecture"] = platform.machine()[:64]
    report["tools"] = tool_versions(find, run)
    report["modules"] = [
        {"module": module, "discovery_status": _probe(("modinfo", module), find, run)[0]}
        for module in MODULES
    ]
    protected, known = _default_links(find, run)
    report["default_routes_observed"] = known
    report["interfaces"] = interface_inventory(net_root, protected, known)
    return report


def local_hardware() -> dict:
    return inspect_hardware(platform.system())
