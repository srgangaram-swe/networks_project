"""Collect tool availability without changing interfaces or loading modules."""

import platform
import shutil
import subprocess
from collections.abc import Callable

TOOLS = (
    ("ip", "-V"),
    ("tc", "-V"),
    ("iperf3", "--version"),
    ("tcpdump", "--version"),
    ("ethtool", "--version"),
)


def inspect_tools(
    system: str,
    find: Callable = shutil.which,
    run: Callable = subprocess.run,
) -> dict:
    """Return bounded-time availability checks, not a testbed readiness claim.

    Discard command output: even version banners can include local build paths.
    Kernel support and interface ownership require a separate, reviewed check.
    """
    checks = []
    if system == "Linux":
        for tool, flag in TOOLS:
            executable = find(tool)
            status = "missing"
            if executable is not None:
                try:
                    result = run(
                        [executable, flag],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        check=False,
                    )
                    status = "available" if result.returncode == 0 else "command_failed"
                except subprocess.TimeoutExpired:
                    status = "timeout"
                except OSError:
                    status = "unavailable"
            checks.append({"tool": tool, "status": status})
    return {
        "schema_version": 1,
        "platform": system,
        "status": "inspection_only" if system == "Linux" else "unsupported_platform",
        "network_changes": False,
        "ready_for_experiment": False,
        "checks": checks,
        "remaining_checks": [
            "owner_permission",
            "equipment_booking",
            "kernel_qdisc_support",
            "isolated_interfaces",
            "driver_and_offload_settings",
            "recorded_tool_versions",
            "namespace_setup_and_cleanup",
        ],
    }


def local_inventory() -> dict:
    return inspect_tools(platform.system())
