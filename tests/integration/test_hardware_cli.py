import json
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class HardwareCliTests(unittest.TestCase):
    def invoke(self, script, *args, timeout=15):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def test_recorded_contract_and_plan_are_portable(self):
        result = self.invoke("verify_testbed_contract.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["eligible_for_primary"])
        result = self.invoke("nucbox_smoke.py", "plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["purpose"], "unloaded_setup_and_cleanup_only")

    def test_corrupt_contract_has_a_useful_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"
            path.write_text("{}")
            result = self.invoke("verify_testbed_contract.py", "--contract", str(path))
            self.assertEqual(result.returncode, 2)
            self.assertIn("contract differs", result.stderr)

    def test_missing_authorization_never_creates_output(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "smoke"
            result = self.invoke("nucbox_smoke.py", "run", "--output", str(output))
            self.assertEqual(result.returncode, 2)
            self.assertIn("authorized-isolated-host", result.stderr)
            self.assertFalse(output.exists())
        result = self.invoke("nucbox_smoke.py", "run")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--output", result.stderr)

    def test_read_only_hardware_inspection_does_not_certify_readiness(self):
        result = self.invoke("inspect_hardware.py", timeout=65)
        self.assertEqual(result.returncode, 0 if platform.system() == "Linux" else 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["network_changes"])
        self.assertFalse(report["ready_for_experiment"])
        for field in ("hostname", "serial_number", "mac_address"):
            self.assertNotIn(field, result.stdout)
