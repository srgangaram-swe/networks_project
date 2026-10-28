"""Deterministic paired blocks, saved before any experiment starts."""

import random
from dataclasses import asdict, dataclass

from src.experiment_config import ExperimentConfig


@dataclass(frozen=True)
class Cell:
    block: int
    policy: str
    load_fraction: float
    flows: int

    @property
    def cell_id(self) -> str:
        load = int(self.load_fraction * 100)
        return f"b{self.block:03d}-{self.policy}-l{load:03d}-f{self.flows:02d}"

    @property
    def baseline_id(self) -> str:
        return f"b{self.block:03d}-{self.policy}-l000-f00"


def make_schedule(config: ExperimentConfig) -> dict:
    """O(C) time and memory for C cells, bounded by configuration's 10,000 limit."""
    if config.repetitions != config.unloaded_repetitions_per_policy:
        raise ValueError("paired blocks require equal loaded and unloaded repetition counts")
    randomizer = random.Random(config.random_seed)
    cells = []
    for block in range(1, config.repetitions + 1):
        policies = list(config.policies)
        randomizer.shuffle(policies)
        for policy in policies:
            conditions = [(0.0, 0)] + [
                (load, flows)
                for load in config.background_load_fractions
                for flows in config.background_flow_counts
            ]
            randomizer.shuffle(conditions)
            for load, flows in conditions:
                cell = Cell(block, policy, load, flows)
                cells.append(
                    {**asdict(cell), "cell_id": cell.cell_id, "baseline_id": cell.baseline_id}
                )
    if len({cell["cell_id"] for cell in cells}) != len(cells):
        raise ValueError("load values collide in percentage-based cell identifiers")
    return {"schema_version": 1, "seed": config.random_seed, "cells": cells}
