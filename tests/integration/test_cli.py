import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CliTests(unittest.TestCase):
    def run_config(self, path):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/validate_config.py"), str(path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_valid_plan_has_no_network_changes(self):
        result = self.run_config(ROOT / "configs/primary.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["status"], "valid_plan")
        self.assertFalse(summary["network_changes"])
        self.assertEqual(summary["total_runs"], 280)

    def test_missing_file_and_invalid_payloads_fail_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            self.assertEqual(self.run_config(path).returncode, 2)
            for payload in ('{"schema_version":1,"schema_version":1}', "{", "[]", " " * 65537):
                path.write_text(payload)
                result = self.run_config(path)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Invalid configuration:", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_branch_policy_reads_event_without_shell_expansion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "event.json"
            for base, head, expected in (("dev", "feat/12-work", 0), ("main", "dev", 1)):
                path.write_text(
                    json.dumps(
                        {
                            "pull_request": {
                                "base": {"ref": base, "repo": {"full_name": "owner/repo"}},
                                "head": {"ref": head, "repo": {"full_name": "owner/repo"}},
                            }
                        }
                    )
                )
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/branch_policy.py")],
                    env={
                        **os.environ,
                        "GITHUB_EVENT_NAME": "pull_request",
                        "GITHUB_EVENT_PATH": str(path),
                    },
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(result.returncode, expected, result.stdout)
