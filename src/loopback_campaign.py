"""A small real-socket campaign with no shaping or physical-network claims."""

import random
from dataclasses import asdict

from src.artifacts import atomic_json, digest
from src.diagnostics import export_diagnostics
from src.run_bundle import source_identity
from src.trial import ROOT, TrialConfig, run_trial


def loopback_plan(transport="udp", rpc_diagnostics=False, seed=561):
    base = TrialConfig(
        measurement_seconds=10,
        warmup_seconds=2,
        transport=transport,
        rpc_diagnostics=rpc_diagnostics,
    )
    cells = []
    randomizer = random.Random(seed)
    for block in (1, 2):
        loads = [0, 110_000_000]
        randomizer.shuffle(loads)
        for load in loads:
            cells.append(
                {
                    "block": block,
                    "configuration": {
                        **asdict(base),
                        "aggregate_bps": load,
                        "flows": int(load > 0),
                    },
                }
            )
    return {
        "kind": "loopback_diagnostics",
        "source": source_identity(ROOT),
        "transport": transport,
        "rpc_diagnostics": rpc_diagnostics,
        "seed": seed,
        "cells": cells,
        "eligible_for_primary": False,
    }


def collect_loopback(output, plan, cancel, trace):
    directory = output / "collection"
    directory.mkdir(mode=0o700)
    runs, attempts = [], []
    for index, cell in enumerate(plan["cells"], 1):
        if cancel.is_set():
            raise InterruptedError("loopback campaign cancelled before the next trial")
        target = directory / f"trial-{index:03d}"
        attempt = {"directory": target.name, "block": cell["block"], "state": "running"}
        attempts.append(attempt)
        atomic_json(directory / "progress.json", {"attempts": attempts})
        with trace.stage(f"loopback_trial_{index}"):
            run_trial(target, TrialConfig(**cell["configuration"]), cancel)
        attempt.update(state="completed", manifest_sha256=digest(target / "manifest.json"))
        atomic_json(directory / "progress.json", {"attempts": attempts})
        runs.append(target)
    with trace.stage("loopback_export_and_analysis"):
        from analysis.diagnostic_report import analyze_loopback, analyze_rpc

        export_diagnostics(runs, output / "export")
        analyze_loopback(runs, output / "analysis")
        if plan["rpc_diagnostics"]:
            analyze_rpc(runs, output / "rpc-analysis")
