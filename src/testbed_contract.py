"""Detect changes to the candidate namespace contract before network mutation."""

import hashlib
import shlex
from pathlib import Path

from src.artifacts import json_bytes, read_json
from src.experiment_config import POLICIES
from src.queue_policy import policy_commands
from src.topology import ROLES, Topology, setup_commands

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "configs/namespace-contract-v1.json"


def candidate_contract() -> dict:
    """Return O(C) bytes for the fixed C planned commands, without executing them.

    A constant token removes run-specific names from the comparison. Command
    strings are for review only; execution still uses the original argv plans.
    Scientific acceptance and machine-specific version pins remain separate.
    """
    topology = Topology("000000000000")
    setup = [("ip", "netns", "add", topology.namespace(role)) for role in ROLES]
    setup.extend(setup_commands(topology))
    return {
        "schema_version": 1,
        "contract_id": "namespace-v1",
        "status": "candidate_pending_team_review",
        "eligible_for_primary": False,
        "measurement_kind": "virtual_testbed",
        "host_interfaces_modified": False,
        "topology_commands": [shlex.join(command) for command in setup],
        "policy_commands": {
            policy: [shlex.join(command) for command in policy_commands(topology, policy)]
            for policy in sorted(POLICIES)
        },
    }


def verify_contract(path: Path = CONTRACT_PATH) -> dict:
    """Require an exact, typed match with the recorded candidate before setup.

    The 64 KiB input limit bounds parsing and comparison. Canonical JSON also
    distinguishes booleans from integers, unlike Python mapping equality.
    This checks source/configuration agreement, not hardware or team approval.
    """
    recorded = read_json(path, 64 * 1024)
    encoded = json_bytes(recorded)
    if encoded != json_bytes(candidate_contract()):
        raise ValueError("namespace contract differs from command plans; review both before setup")
    return {
        "contract_id": "namespace-v1",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "status": "candidate_pending_team_review",
        "eligible_for_primary": False,
    }
