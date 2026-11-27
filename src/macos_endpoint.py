"""Read-only checks and bounded workloads on explicitly configured Mac Ethernet links.

Network configuration belongs to the operator. Workers never alter interfaces,
routes, firewalls or global TCP settings. An exclusive lease prevents concurrent
trials; shared execution locks keep cleanup from racing a live workload.
"""

import fcntl
import hashlib
import os
import platform
import re
import socket
import time
from contextlib import contextmanager
from pathlib import Path

from src.artifacts import atomic_json, read_json
from src.physical_profile import _role, role_path
from src.processes import run_command
from src.topology import CLIENT_ADDRESS, SERVER_ADDRESS, Topology


def _text(args):
    return run_command(args, timeout=5, limit=16384).stdout.decode("utf-8")


def route_fields(text):
    return dict(re.findall(r"^\s*(destination|gateway|interface):\s*(\S+)\s*$", text, re.M))


def check_link(text, hardware, interface, address, *, require_active=True):
    """Validate bounded command output before allowing traffic; O(B) time/space."""
    ports = hardware.split("\n\n")
    matching = [p for p in ports if f"Device: {interface}\n" in p + "\n"]
    label = matching[0].splitlines()[0] if len(matching) == 1 else ""
    if not re.search(r"(Ethernet|LAN)", label) or "Wi-Fi" in label or "Bridge" in label:
        raise PermissionError("select a dedicated wired Ethernet adapter, not Wi-Fi or a bridge")
    flags = re.search(r"flags=\d+<([^>]+)> mtu (\d+)", text)
    addresses = re.findall(r"^\s*inet (\S+) netmask (\S+)", text, re.M)
    mac = re.search(r"^\s*ether ([0-9a-f:]{17})", text, re.M)
    if not flags or "UP" not in flags[1].split(",") or flags[2] != "1500":
        raise PermissionError("dedicated Ethernet must be up with MTU 1500")
    if addresses != [(address, "0xfffffffc")] or not mac:
        raise PermissionError("dedicated Ethernet needs the exact /30 address and a MAC address")
    if require_active and "status: active" not in text:
        raise PermissionError("dedicated Ethernet needs an active cable before traffic starts")
    return mac[1]


def inspect(item, role, *, require_active=False):
    _role(role, item)
    if platform.system() != "Darwin" or item.get("platform") != "macos" or role == "router":
        raise PermissionError("this helper requires a configured macOS client or server")
    interface = item["interfaces"]["eth0"]
    address, peer, gateway = (
        (CLIENT_ADDRESS, SERVER_ADDRESS, "10.203.0.1")
        if role == "client"
        else (SERVER_ADDRESS, CLIENT_ADDRESS, "10.203.0.5")
    )
    default = route_fields(_text(("/sbin/route", "-n", "get", "default")))
    route = route_fields(_text(("/sbin/route", "-n", "get", peer)))
    if not default.get("interface") or default["interface"] == interface:
        raise PermissionError("keep a separate management/default route, normally Wi-Fi")
    if route.get("interface") != interface or route.get("gateway") != gateway:
        raise PermissionError("the peer needs an explicit route through the NucBox Ethernet link")
    mac = check_link(
        _text(("/sbin/ifconfig", interface)),
        _text(("/usr/sbin/networksetup", "-listallhardwareports")),
        interface,
        address,
        require_active=require_active,
    )
    version = _text((item["iperf3"], "--version")).splitlines()[0]
    return {
        "platform": "Darwin",
        "network_host": hashlib.sha256(socket.gethostname().encode()).hexdigest(),
        "interfaces": [{"ifindex": socket.if_nametoindex(interface), "mac": mac}],
        "interface": interface,
        "address": address,
        "peer_route": route,
        "iperf3": version,
        "kernel": platform.release(),
        "network_changes": False,
    }


@contextmanager
def lock(path, *, shared=False):
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(stream, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "endpoint still has an active worker; retain the lease"
                    ) from None
                time.sleep(0.02)
        yield


def _directory(item, role, token):
    directory = role_path(item, token, role)
    info = directory.lstat()
    if directory.is_symlink() or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError("endpoint lease must be private and owned by the calling account")
    return directory


def prepare(item, role, token):
    evidence = inspect(item, role)
    parent = Path(item["repository"]) / ".local"
    parent.mkdir(mode=0o700, exist_ok=True)
    with lock(parent / f"macos-{role}.lock"):
        active = parent / f"macos-{role}-active.json"
        if active.exists():
            raise FileExistsError("a retained endpoint lease needs cleanup before another trial")
        directory = role_path(item, token, role)
        directory.mkdir(mode=0o700)
        state = {
            "token": token,
            "role": role,
            "item": item,
            "evidence": evidence,
            "phase": "active",
        }
        atomic_json(directory / "lease.json", state)
        atomic_json(active, {"token": token})
    return state


def workload(item, args):
    root = Path(item["repository"])
    if not isinstance(args, list) or any(not isinstance(x, str) or "\0" in x for x in args):
        raise ValueError("endpoint arguments must be NUL-free strings")
    if not args or len(args) > 64 or sum(map(len, args)) > 8192:
        raise ValueError("endpoint command exceeds its argument budget")
    if args[0] == item["iperf3"]:
        return tuple(args)
    if tuple(args[:2]) not in {
        (str(root / ".venv/bin/python"), str(root / "scripts" / name))
        for name in ("foreground.py", "rpc.py")
    }:
        raise PermissionError("only the foreground/RPC workloads and configured iperf3 are allowed")
    return tuple(args)


def act(action, request, cancel):
    item, role = request["item"], request["role"]
    _role(role, item)
    token = Topology(request["token"]).token
    if action == "inspect":
        return inspect(item, role)
    if action == "prepare":
        return prepare(item, role, token)
    directory = _directory(item, role, token)
    with lock(directory / "lock", shared=action == "exec"):
        state = read_json(directory / "lease.json", 65536)
        if (state["token"], state["role"], state["item"]) != (token, role, item):
            raise PermissionError("endpoint lease differs from the request")
        if action == "exec":
            if (
                state["phase"] != "active"
                or inspect(item, role, require_active=True) != state["evidence"]
            ):
                raise PermissionError("endpoint configuration changed during the trial")
            from src.physical_worker import _forward

            return run_command(
                workload(item, request["args"]),
                timeout=180,
                limit=1024 * 1024,
                check=False,
                observe=_forward,
                stop=cancel,
            ).returncode
        if action != "cleanup":
            raise ValueError("unsupported endpoint action")
        with lock(directory.parent / f"macos-{role}.lock"):
            active = directory.parent / f"macos-{role}-active.json"
            if active.exists():
                if read_json(active, 4096) != {"token": token}:
                    raise PermissionError("a different trial owns the endpoint")
                active.unlink()
            state["phase"] = "closed"
            atomic_json(directory / "lease.json", state)
        return state
