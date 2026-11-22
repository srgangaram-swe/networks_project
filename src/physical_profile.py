"""Validate dedicated-interface profiles and build quoted, noninteractive SSH commands."""

import os
import re
import shlex
from pathlib import Path, PurePosixPath

from src.artifacts import json_bytes, parse_json
from src.topology import ROLES, Topology

INTERFACES = {"client": {"eth0"}, "router": {"to-client", "to-server"}, "server": {"eth0"}}


def validate_profile(raw: object) -> dict:
    if not isinstance(raw, dict) or raw.keys() != {"schema_version", "roles"}:
        raise ValueError("physical profile needs schema_version and three roles")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ValueError("unsupported physical profile version")
    if not isinstance(raw["roles"], dict) or raw["roles"].keys() != set(ROLES):
        raise ValueError("physical profile needs client, router, and server")
    used = set()
    for role, item in raw["roles"].items():
        _role(role, item)
        for interface in item["interfaces"].values():
            identity = (item["host"], interface)
            if identity in used:
                raise ValueError("an interface cannot belong to two roles")
            used.add(identity)
    return raw


def _role(role: str, item: object) -> None:
    if (
        not isinstance(item, dict)
        or not {"host", "repository", "interfaces"} <= item.keys()
        or not item.keys()
        <= {"host", "repository", "interfaces", "ssh_config", "platform", "iperf3"}
    ):
        raise ValueError("each role needs host, repository, and interfaces")
    if not isinstance(item["host"], str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}", item["host"]
    ):
        raise ValueError("host must be local or a configured SSH alias")
    repository = item["repository"]
    if not isinstance(repository, str) or not repository.startswith("/") or len(repository) > 512:
        raise ValueError("repository must be an absolute Unix path")
    if ".." in PurePosixPath(repository).parts or any(c in repository for c in ("\0", "\n", "\r")):
        raise ValueError("repository path must be normalized and single-line")
    _platform_options(role, item)
    interfaces = item["interfaces"]
    if not isinstance(interfaces, dict) or interfaces.keys() != INTERFACES[role]:
        raise ValueError(f"incorrect interface roles for {role}")
    for name in interfaces.values():
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}", name)
            or name in {"lo", "lo0"}
        ):
            raise ValueError("choose a dedicated Ethernet interface, not loopback")


def _platform_options(role, item):
    if item.get("platform", "linux") not in {"linux", "macos"}:
        raise ValueError("role platform must be linux or macos")
    if item.get("platform") == "macos":
        executable = item.get("iperf3")
        if (
            role == "router"
            or not isinstance(executable, str)
            or not re.fullmatch(r"/[A-Za-z0-9_./-]{1,511}", executable)
        ):
            raise ValueError("macOS endpoints need an absolute iperf3 path; the router needs Linux")
    if "ssh_config" in item:
        path = item["ssh_config"]
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or len(path) > 512
            or any(c in path for c in ("\0", "\r", "\n"))
        ):
            raise ValueError("SSH configuration must be an absolute, single-line path")


def payload(value: dict) -> str:
    data = json_bytes(value)
    if len(data) > 16384:
        raise ValueError("remote request exceeds 16 KiB")
    return data.decode()


def decode_payload(value: str) -> dict:
    data = value.encode()
    if len(data) > 16384:
        raise ValueError("remote request exceeds 16 KiB")
    result = parse_json(data)
    if not isinstance(result, dict):
        raise ValueError("remote request must be an object")
    return result


def host_command(item: dict, args: tuple[str, ...], *, privileged: bool = False) -> tuple[str, ...]:
    command = (("sudo", "-n") if privileged else ()) + args
    if item["host"] == "local":
        return args if privileged and os.geteuid() == 0 else command
    return (
        "ssh",
        *(("-F", item["ssh_config"]) if "ssh_config" in item else ()),
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=2",
        "--",
        item["host"],
        shlex.join(command),
    )


def worker_command(profile: dict, role: str, action: str, token: str, **details) -> tuple[str, ...]:
    Topology(token)
    item = profile["roles"][role]
    root = PurePosixPath(item["repository"])
    request = {"role": role, "token": token, "item": item, **details}
    macos = item.get("platform") == "macos"
    return host_command(
        item,
        (
            str(root / ".venv/bin/python"),
            str(root / "scripts" / ("macos_host.py" if macos else "physical_host.py")),
            action,
            "--request",
            payload(request),
        ),
        privileged=not macos,
    )


def role_path(item: dict, token: str, role: str) -> Path:
    Topology(token)
    if role not in ROLES:
        raise ValueError("unsupported physical role")
    return Path(item["repository"]) / ".local" / f"physical-{token}-{role}"


def check_inspections(inspections):
    used = set()
    for result in inspections:
        for link in result["interfaces"]:
            identity = (result["network_host"], link["ifindex"])
            if identity in used:
                raise ValueError("SSH aliases resolve to the same dedicated interface")
            used.add(identity)


def profile_mode(profile):
    platforms = {role: item.get("platform", "linux") for role, item in profile["roles"].items()}
    if platforms == {"client": "macos", "router": "linux", "server": "macos"}:
        return "macos"
    if set(platforms.values()) == {"linux"}:
        return "physical"
    raise ValueError("choose three Linux hosts or two Mac endpoints and one Linux router")
