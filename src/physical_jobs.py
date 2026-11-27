"""Register remote workers by process start identity before they launch workloads."""

import fcntl
import os
import signal
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from src.artifacts import atomic_json, read_bytes, read_json


@contextmanager
def lease_lock(directory):
    descriptor = os.open(directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("physical lease lock did not become available") from None
                time.sleep(0.02)
        yield


def process_start(pid: int) -> str | None:
    if type(pid) is not int or not 1 < pid < 2**31:
        raise PermissionError("invalid physical worker PID")
    try:
        return read_bytes(Path(f"/proc/{pid}/stat"), 4096).decode().rsplit(")", 1)[1].split()[19]
    except FileNotFoundError:
        return None


def register_job(lease) -> tuple:
    with lease_lock(lease.directory):
        current = read_json(lease.directory / "lease.json", 65536)
        if current["phase"] != "active":
            raise PermissionError("physical lease is not active")
        directory = lease.directory / "jobs"
        directory.mkdir(mode=0o700, exist_ok=True)
        if len(list(directory.iterdir())) >= 256:
            raise ValueError("physical worker budget exceeded")
        path = directory / f"{uuid.uuid4().hex}.json"
        record = {"pid": os.getpid(), "start": process_start(os.getpid()), "state": "running"}
        atomic_json(path, record)
    return path, record


def stop_jobs(lease):
    with lease_lock(lease.directory):
        lease.state["phase"] = "closing"
        lease.save()
        jobs = list((lease.directory / "jobs").glob("*.json"))
        if len(jobs) > 256:
            raise ValueError("physical worker registry exceeds its bound")
        for path in jobs:
            record = read_json(path, 4096)
            if record["state"] == "running" and process_start(record["pid"]) == record["start"]:
                if (
                    type(record["pid"]) is not int
                    or record["pid"] <= 1
                    or record["pid"] == os.getpid()
                ):
                    raise PermissionError("invalid owned worker identity")
                _signal_owned(record)
    deadline = time.monotonic() + 8
    for path in jobs:
        record = read_json(path, 4096)
        while record["state"] == "running" and process_start(record["pid"]) == record["start"]:
            if time.monotonic() >= deadline:
                raise TimeoutError("owned physical worker did not stop; retain its journal")
            time.sleep(0.02)
            record = read_json(path, 4096)


def _signal_owned(record):
    # A pidfd pins the process identity across the verification/signal boundary.
    try:
        descriptor = os.pidfd_open(record["pid"])
    except ProcessLookupError:
        return
    try:
        if process_start(record["pid"]) == record["start"]:
            signal.pidfd_send_signal(descriptor, signal.SIGTERM)
    except ProcessLookupError:
        return
    finally:
        os.close(descriptor)
