"""Bounded JSON files and atomic publication on Unix filesystems."""

import hashlib
import json
import math
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

MAX_JSON_BYTES = 32 * 1024 * 1024


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON number exceeds the finite floating-point range")
    return number


def read_bytes(path: Path, limit: int = MAX_JSON_BYTES) -> bytes:
    """Read a regular file without following its final symlink, in O(limit) space."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"expected a regular file: {path.name}")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"file exceeds the {limit}-byte limit: {path.name}")
    return data


def parse_json(data: bytes) -> Any:
    try:
        return json.loads(
            data,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("JSON must be UTF-8 with bounded nesting") from exc


def read_json(path: Path, limit: int = MAX_JSON_BYTES) -> Any:
    return parse_json(read_bytes(path, limit))


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def atomic_json(path: Path, value: Any) -> None:
    """Replace one owned artifact after fsync; incomplete output never replaces it."""
    data = json_bytes(value)
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("JSON output exceeds the artifact limit")
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def digest(path: Path) -> str:
    return hashlib.sha256(read_bytes(path)).hexdigest()
