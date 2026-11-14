"""Bounded operations on one explicitly configured, isolated Linux role."""

import argparse
import hashlib
import json
import os
import pwd
import signal
import sys
from pathlib import Path
from threading import Event

from src.artifacts import atomic_json, read_bytes
from src.physical_commands import allowed_kernel_commands
from src.physical_jobs import register_job, stop_jobs
from src.physical_lease import PhysicalLease, inspect_interfaces
from src.physical_profile import _role, decode_payload
from src.topology import ROLES, Topology
from src.topology_runtime import require_linux


def execute(request: dict, cancel: Event):
    lease = PhysicalLease.load(request["item"], request["role"], request["token"])
    lease.verify()
    args = request["args"]
    if (
        not isinstance(args, list)
        or not args
        or any(not isinstance(a, str) or "\0" in a for a in args)
    ):
        raise ValueError("physical command requires NUL-free arguments")
    args = tuple(args)
    root = Path(request["item"]["repository"])
    workload = args[0] == "iperf3" or args[:2] == (
        str(root / ".venv/bin/python"),
        str(root / "scripts/foreground.py"),
    )
    observer = args[:2] == (str(root / ".venv/bin/python"), str(root / "scripts/tcp_observer.py"))
    if observer:
        _observer_paths(request, args, root)
    if not (workload or observer) and args not in allowed_kernel_commands(
        request["role"], request["token"]
    ):
        raise PermissionError("physical kernel command is outside the reviewed topology plan")
    if workload:
        bundle = root / ".local/physical-runs" / request["token"]
        owner_path = bundle if request["role"] == "client" and bundle.exists() else root
        owner = pwd.getpwuid(owner_path.stat().st_uid).pw_name
        args = ("runuser", "-u", owner, "--", *args)
    path, record = register_job(lease)
    primary = None
    try:
        result = lease.execute(
            args,
            timeout=180,
            limit=1024 * 1024,
            check=False,
            observe=lambda name, data: _forward(name, data),
            stop=cancel,
        )
        record["state"] = "completed"
        record["returncode"] = result.returncode
        return result.returncode
    except BaseException as error:
        primary = error
        raise
    finally:
        if record["state"] != "completed":
            record["state"] = "failed"
        try:
            atomic_json(path, record)
        except (OSError, ValueError) as persistence:
            if primary is None:
                raise
            primary.add_note(f"retaining worker completion also failed: {persistence}")


def _observer_paths(request, args, root):
    if request["role"] != "client":
        raise PermissionError("passive TCP observation belongs on the client")
    parent = root / ".local/physical-runs" / request["token"]
    for option, name in (("--output", "tcp-observer.json"), ("--events-fifo", "events.fifo")):
        if option not in args and option == "--events-fifo":
            continue
        index = args.index(option)
        if index + 1 >= len(args) or Path(args[index + 1]) != parent / name:
            raise PermissionError("passive TCP observer paths differ from its owned client bundle")


def _forward(name, data):
    stream = sys.stdout.buffer if name == "stdout" else sys.stderr.buffer
    stream.write(data)
    stream.flush()


def action(name: str, request: dict, cancel: Event):
    require_linux()
    role = request["role"]
    if role not in ROLES:
        raise ValueError("unsupported physical role")
    _role(role, request["item"])
    Topology(request["token"])
    if name == "inspect":
        identity = read_bytes(Path("/proc/sys/kernel/random/boot_id"), 256)
        namespace = os.stat("/proc/self/ns/net")
        return {
            "interfaces": inspect_interfaces(request["item"]),
            "platform": "Linux",
            "network_host": hashlib.sha256(identity + str(namespace.st_ino).encode()).hexdigest(),
        }
    if name == "prepare":
        return PhysicalLease.prepare(request["item"], role, request["token"]).state
    if name == "exec":
        return execute(request, cancel)
    lease = PhysicalLease.load(request["item"], role, request["token"])
    stop_jobs(lease)
    lease.cleanup()
    return lease.state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "prepare", "exec", "cleanup"))
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    cancel = Event()
    previous = {
        number: signal.signal(number, lambda *_: cancel.set())
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    }
    try:
        result = action(args.action, decode_payload(args.request), cancel)
        if args.action == "exec":
            return result
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"Physical host failed: {error}", file=sys.stderr)
        return 2
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
