"""Explicitly enabled tests for an isolated Linux host. Never run against host NICs."""

import os
import platform
import tempfile
import unittest
from pathlib import Path

from src.artifacts import read_json
from src.bundle_validation import validate_bundle
from src.experiment_config import POLICIES
from src.trial import TrialConfig, run_trial

ENABLED = (
    platform.system() == "Linux"
    and os.geteuid() == 0
    and os.environ.get("NETWORKS_RUN_PRIVILEGED") == "1"
)


@unittest.skipUnless(
    ENABLED,
    "requires root on isolated Linux and NETWORKS_RUN_PRIVILEGED=1; issues #3, #5, #6, #11",
)
class NamespaceTests(unittest.TestCase):
    def test_every_queue_profile_runs_and_leaves_no_owned_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            for policy in sorted(POLICIES):
                path = Path(directory) / policy
                config = TrialConfig(
                    mode="namespace", policy=policy, measurement_seconds=2, warmup_seconds=1
                )
                run_trial(path, config)
                self.assertTrue(validate_bundle(path)["integrity_valid"])
                self.assertEqual(read_json(path / "topology/ownership.json")["owned"], {})
                capture = read_json(path / "foreground.json")
                replies = [row for row in capture["records"] if row["received_ns"] is not None]
                self.assertTrue(replies)
                self.assertGreater(
                    min(row["received_ns"] - row["sent_ns"] for row in replies), 18_000_000
                )


if __name__ == "__main__":
    unittest.main()
