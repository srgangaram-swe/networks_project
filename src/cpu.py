"""Shared-host Linux CPU accounting without double-counting guest ticks."""

import platform
from pathlib import Path


def parse_cpu(line: str) -> tuple[int, ...]:
    fields = line.split()
    if not 9 <= len(fields) <= 11 or fields[0] != "cpu":
        raise ValueError("expected aggregate Linux CPU counters")
    values = tuple(int(value) for value in fields[1:9])
    if any(value < 0 for value in values):
        raise ValueError("CPU counters must be nonnegative")
    return values


def snapshot_cpu() -> tuple[int, ...] | None:
    if platform.system() != "Linux":
        return None
    with Path("/proc/stat").open() as stream:
        return parse_cpu(stream.readline(4096))


def cpu_usage(before: tuple[int, ...] | None, after: tuple[int, ...] | None) -> dict:
    if before is None or after is None:
        return {"scope": "unavailable", "busy_percent": None, "iowait_percent": None}
    if len(before) != 8 or len(after) != 8:
        raise ValueError("CPU snapshot requires eight counters")
    delta = [end - start for start, end in zip(before, after, strict=True)]
    if any(value < 0 for value in delta) or sum(delta) == 0:
        raise ValueError("CPU counters reset or did not advance")
    total = sum(delta)
    busy = total - delta[3] - delta[4]
    return {
        "scope": "shared_host",
        "busy_percent": 100 * busy / total,
        "iowait_percent": 100 * delta[4] / total,
    }
