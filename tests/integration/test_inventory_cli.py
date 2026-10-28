import json
import platform
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class InventoryCliTests(unittest.TestCase):
    def test_real_cli_reports_platform_without_private_machine_identity(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/inspect_testbed.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=35,
            check=False,
        )
        self.assertEqual(result.returncode, 0 if platform.system() == "Linux" else 2)
        report = json.loads(result.stdout)
        self.assertEqual(report["platform"], platform.system())
        self.assertFalse(report["network_changes"])
        self.assertFalse(report["ready_for_experiment"])
        self.assertEqual(result.stderr, "")
        self.assertNotIn("hostname", report)
        self.assertNotIn("interfaces", report)
