"""Exercise the real launcher without changing the developer's network."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class MacTopologyCLITests(unittest.TestCase):
    def command(self, *args):
        return subprocess.run(
            ["sh", "scripts/run_pipeline.sh", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def test_shell_plans_mac_hardware_and_keeps_simulation_separate(self):
        result = self.command(
            "--topology", "macos", "--plan", "--profile", "configs/macos-profile.example.json"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["kind"], "macos_testbed_diagnostics")
        self.assertFalse(value["eligible_for_primary"])
        self.assertEqual(len(value["schedule"]["cells"]), 16)
        result = self.command("--topology", "local", "--plan")
        self.assertEqual(json.loads(result.stdout)["measurement_slots"], 240000)

    def test_missing_profile_and_unauthorized_execution_fail_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "must-not-exist"
            for extra in ([], ["--profile", "configs/macos-profile.example.json"]):
                result = self.command("--topology", "macos", "--output", str(output), *extra)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Pipeline failed", result.stderr)
                self.assertFalse(output.exists())
