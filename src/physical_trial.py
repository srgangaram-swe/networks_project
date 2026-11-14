"""Coordinate a physical trial on the client host and retrieve only named artifacts."""

import argparse
import json
import signal
import sys
from pathlib import Path
from threading import Event

from src.artifacts import read_bytes
from src.bundle_validation import ARTIFACTS, OPTIONAL_ARTIFACTS
from src.physical_backend import PhysicalBackend
from src.physical_profile import _role, decode_payload, validate_profile
from src.run_bundle import source_identity
from src.topology import Topology
from src.trial import ROOT, TrialConfig, run_trial


def act(action, request, cancel):
    if action == "identity":
        _role(request["role"], request["item"])
        root = Path(request["item"]["repository"])
        if root.resolve() != ROOT.resolve():
            raise ValueError("physical source path differs from the running checkout")
        (root / ".local").mkdir(mode=0o700, exist_ok=True)
        return source_identity(root)
    profile = validate_profile(request["profile"])
    token = Topology(request["token"]).token
    parent = ROOT / ".local/physical-runs"
    parent.mkdir(mode=0o700, exist_ok=True)
    output = parent / token
    if action == "fetch":
        name = request["artifact"]
        if name not in ARTIFACTS | OPTIONAL_ARTIFACTS | {"manifest.json"}:
            raise ValueError("only validated trial artifact names can be retrieved")
        return read_bytes(output / name)
    config = TrialConfig(**request["configuration"])
    if config.mode != "physical":
        raise ValueError("physical trial requires the physical mode")
    return run_trial(
        output,
        config,
        cancel,
        backend=PhysicalBackend(profile, token, config.policy, transport=config.transport),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("identity", "run", "fetch"))
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    cancel = Event()
    previous = {
        number: signal.signal(number, lambda *_: cancel.set())
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    }
    try:
        result = act(args.action, decode_payload(args.request), cancel)
        if isinstance(result, bytes):
            sys.stdout.buffer.write(result)
        else:
            print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"Physical trial failed: {error}", file=sys.stderr)
        return 2
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
