"""Bounded progress records and monotonic stage measurements."""

import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from src.artifacts import atomic_json

LOGGER = logging.getLogger("experiment")
MAX_EVENTS = 4096


class Telemetry:
    def __init__(self, directory: Path | None):
        self.directory = directory
        self.stages: list[dict] = []
        self.events = 0
        self.started = time.monotonic()

    def event(self, name: str, **details) -> None:
        if self.events >= MAX_EVENTS:
            raise ValueError("pipeline event budget exceeded")
        record = {
            "event": name,
            "utc": datetime.now(UTC).isoformat(),
            "elapsed_seconds": time.monotonic() - self.started,
            "pid": os.getpid(),
            **details,
        }
        serialized = json.dumps(record, allow_nan=False, sort_keys=True) + "\n"
        if len(serialized.encode()) > 4096:
            raise ValueError("pipeline event exceeds its 4 KiB byte budget")
        if self.directory is not None:
            with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(serialized)
        self.events += 1
        LOGGER.info("%s %s", name, json.dumps(details, sort_keys=True))

    def save(self) -> None:
        if self.directory is None:
            return
        atomic_json(
            self.directory / "timings.json",
            {"clock": "monotonic", "process_cpu_scope": "coordinator", "stages": self.stages},
        )

    @contextmanager
    def stage(self, name: str):
        started, cpu = time.monotonic(), time.process_time()
        row = {"stage": name, "state": "running"}
        self.stages.append(row)
        self.event("stage_started", stage=name)
        primary = None
        try:
            yield
            row["state"] = "completed"
        except BaseException as error:
            primary = error
            row.update(state="failed", error_type=type(error).__name__)
            raise
        finally:
            row.update(
                wall_seconds=time.monotonic() - started,
                process_cpu_seconds=time.process_time() - cpu,
            )
            try:
                self.save()
                self.event("stage_finished", **row)
            except (OSError, ValueError) as persistence:
                if primary is None:
                    raise
                primary.add_note(f"retaining stage metrics also failed: {persistence}")
