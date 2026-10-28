"""Ownership-checked Linux mutations and a durable cleanup journal."""

import fcntl
import os
import platform
from collections.abc import Callable
from pathlib import Path

from src.artifacts import atomic_json, read_json
from src.processes import CommandError, run_command
from src.topology import ROLES, Topology, setup_commands


def namespace_identity(name: str) -> list[int] | None:
    try:
        info = (Path("/var/run/netns") / name).stat()
    except FileNotFoundError:
        return None
    return [info.st_dev, info.st_ino]


def require_linux() -> None:
    if platform.system() != "Linux" or os.geteuid() != 0:
        raise PermissionError("network mutations require root on an isolated Linux host")


def _read_state(directory: Path) -> dict:
    info = directory.lstat()
    if directory.is_symlink() or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError("state directory must be private and owned by the current user")
    state = read_json(directory / "ownership.json", 16384)
    if not isinstance(state, dict) or state.keys() != {"schema_version", "token", "owned"}:
        raise ValueError("invalid topology ownership journal")
    if type(state["schema_version"]) is not int or state["schema_version"] != 1:
        raise ValueError("unsupported ownership schema")
    topology = Topology(state["token"])
    if not isinstance(state["owned"], dict):
        raise ValueError("owned namespaces must be an object")
    allowed = {topology.namespace(role) for role in ROLES}
    for name, identity in state["owned"].items():
        if name not in allowed or not isinstance(identity, list) or len(identity) != 2:
            raise ValueError("journal contains an unexpected namespace")
        if any(type(value) is not int or value < 0 for value in identity):
            raise ValueError("invalid namespace identity")
    return state


class OwnedTopology:
    """Hold an exclusive local lock; never infer ownership from a name alone."""

    def __init__(
        self,
        directory: Path,
        *,
        run: Callable = run_command,
        identity: Callable = namespace_identity,
    ) -> None:
        self.directory = directory
        self.state = _read_state(directory)
        self.topology = Topology(self.state["token"])
        self.run = run
        self.identity = identity
        self.lock = os.open(directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Read after locking as well: another process could have just finished cleanup.
            self.state = _read_state(directory)
        except BaseException:
            os.close(self.lock)
            raise

    @classmethod
    def create(cls, directory: Path, topology: Topology, **kwargs) -> "OwnedTopology":
        directory.mkdir(mode=0o700)
        atomic_json(
            directory / "ownership.json",
            {"schema_version": 1, "token": topology.token, "owned": {}},
        )
        return cls(directory, **kwargs)

    def __enter__(self) -> "OwnedTopology":
        return self

    def __exit__(self, *_args) -> None:
        os.close(self.lock)

    def save(self) -> None:
        atomic_json(self.directory / "ownership.json", self.state)

    def verify(self) -> None:
        expected = {self.topology.namespace(role) for role in ROLES}
        if self.state["owned"].keys() != expected:
            raise ValueError("topology is incomplete")
        for name, identity in self.state["owned"].items():
            if self.identity(name) != identity:
                raise PermissionError(f"namespace ownership changed: {name}")

    def setup(self) -> None:
        if self.state["owned"]:
            raise FileExistsError("topology already has owned resources")
        try:
            for role in ROLES:
                name = self.topology.namespace(role)
                if self.identity(name) is not None:
                    raise FileExistsError(f"namespace already exists: {name}")
                self.run(("ip", "netns", "add", name))
                identity = self.identity(name)
                if identity is None:
                    raise CommandError(f"namespace creation was not observable: {name}")
                self.state["owned"][name] = identity
                self.save()
            self.verify()
            for command in setup_commands(self.topology):
                self.run(command)
        except BaseException as primary:
            try:
                self.cleanup()
            except (OSError, ValueError, RuntimeError) as cleanup:
                primary.add_note(f"cleanup also failed: {cleanup}")
            raise

    def _delete(self, name: str, expected: list[int]) -> None:
        actual = self.identity(name)
        if actual is None:
            return
        if actual != expected:
            raise PermissionError(f"refusing to remove a replaced namespace: {name}")
        processes = self.run(("ip", "netns", "pids", name))
        if processes.stdout.strip():
            raise RuntimeError(f"namespace still contains live processes: {name}")
        self.run(("ip", "netns", "delete", name))
        if self.identity(name) is not None:
            raise RuntimeError(f"namespace survived deletion: {name}")

    def cleanup(self) -> None:
        errors = []
        for name, identity in list(self.state["owned"].items())[::-1]:
            try:
                self._delete(name, identity)
            except (OSError, RuntimeError) as exc:
                errors.append(str(exc))
                continue
            del self.state["owned"][name]
            self.save()
        if errors:
            raise RuntimeError("; ".join(errors))
