"""Exclusive run directories and durable lifecycle evidence."""

import hashlib
import platform
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from src.artifacts import atomic_json, digest, read_bytes
from src.processes import run_command

TRANSITIONS = {
    "created": {"preflight"},
    "preflight": {"setup"},
    "setup": {"warmup"},
    "warmup": {"measurement"},
    "measurement": {"drain"},
    "drain": {"collection"},
    "collection": {"validation"},
    "validation": {"teardown"},
    "teardown": {"completed"},
}


def source_identity(root: Path) -> dict:
    commit = run_command(("git", "-C", str(root), "rev-parse", "HEAD")).stdout.decode().strip()
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("source commit is not a Git SHA-1 identifier")
    dirty = bool(run_command(("git", "-C", str(root), "status", "--porcelain")).stdout)
    paths = sorted(
        path
        for folder in ("src", "scripts", "configs")
        for path in (root / folder).glob("*.py" if folder != "configs" else "*.json")
    )
    paths.extend(root / name for name in ("pyproject.toml", "requirements-dev.txt"))
    checksum = hashlib.sha256()
    for path in paths:
        checksum.update(str(path.relative_to(root)).encode() + b"\0")
        checksum.update(read_bytes(path, 1024 * 1024))
        checksum.update(b"\0")
    return {"commit": commit, "tree_sha256": checksum.hexdigest(), "dirty": dirty}


class RunBundle:
    def __init__(self, directory: Path, configuration: dict, source: dict):
        directory.mkdir(mode=0o700)
        self.directory = directory
        self.manifest = {
            "schema_version": 1,
            "run_id": uuid.uuid4().hex,
            "state": "created",
            "started_utc": datetime.now(UTC).isoformat(),
            "source": source,
            "mode": configuration["mode"],
            "policy": configuration["policy"],
            "units": {"timestamps": "ns", "goodput": "Mb/s", "cpu": "percent"},
            "artifacts": {},
            "history": [],
            "errors": [],
            "phases": None,
            "validity": {"eligible_for_primary": False, "reasons": ["pilot_review_pending"]},
        }
        self.save()
        self.artifact("configuration.json", configuration)
        self.artifact(
            "environment.json",
            {
                "system": platform.system(),
                "kernel": platform.release(),
                "python": sys.version.split()[0],
                "measurement_kind": "loopback_diagnostic"
                if configuration["mode"] == "loopback"
                else "virtual_testbed",
            },
        )

    def save(self) -> None:
        atomic_json(self.directory / "manifest.json", self.manifest)

    def artifact(self, name: str, value: object) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]*\.json", name) or name == "manifest.json":
            raise ValueError("invalid artifact filename")
        if name in self.manifest["artifacts"] or (self.directory / name).exists():
            raise FileExistsError("artifact already exists")
        atomic_json(self.directory / name, value)
        self.register(name)

    def register(self, name: str) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]*\.json", name) or name == "manifest.json":
            raise ValueError("invalid artifact filename")
        if name in self.manifest["artifacts"]:
            raise FileExistsError("artifact is already registered")
        self.manifest["artifacts"][name] = digest(self.directory / name)
        self.save()

    def transition(self, state: str) -> None:
        current = self.manifest["state"]
        if state not in TRANSITIONS.get(current, set()) and state not in {"failed", "cancelled"}:
            raise ValueError(f"invalid lifecycle transition: {current} to {state}")
        if current in {"completed", "failed", "cancelled"}:
            raise ValueError("terminal run state cannot change")
        self.manifest["state"] = state
        self.manifest["history"].append({"state": state, "observed_ns": time.monotonic_ns()})
        self.save()

    def fail(self, error: BaseException, *, cancelled: bool = False) -> None:
        self.manifest["errors"].append(
            {
                "type": type(error).__name__,
                "message": str(error)[:1024],
                "notes": [str(note)[:1024] for note in getattr(error, "__notes__", [])[:10]],
            }
        )
        self.transition("cancelled" if cancelled else "failed")
