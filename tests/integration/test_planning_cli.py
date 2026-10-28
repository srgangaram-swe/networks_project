import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PlanningCliTests(unittest.TestCase):
    def call(self, script, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def test_schedule_is_saved_once_with_all_pairings(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "schedule.json"
            args = (ROOT / "configs/primary.json", "--output", output)
            result = self.call("schedule.py", *args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(json.loads(output.read_text())["cells"]), 280)
            self.assertEqual(self.call("schedule.py", *args).returncode, 2)

    def test_topology_plan_is_read_only_and_mutation_needs_explicit_authority(self):
        result = self.call(
            "testbed.py", "plan", "--policy", "cake_bounded", "--token", "012345abcdef"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertFalse(plan["network_changes"])
        self.assertGreater(len(plan["commands"]), 30)
        self.assertEqual(self.call("testbed.py", "setup").returncode, 2)
        self.assertEqual(self.call("testbed.py", "plan", "--policy", "unsupported").returncode, 2)

    def test_branch_floor_cannot_be_hidden_by_high_line_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "coverage.json"
            for covered, expected in ((89, 1), (90, 0)):
                report.write_text(
                    json.dumps(
                        {
                            "totals": {
                                "covered_branches": covered,
                                "num_branches": 100,
                                "percent_covered": 99,
                            }
                        }
                    )
                )
                self.assertEqual(self.call("check_branch_coverage.py", report).returncode, expected)


if __name__ == "__main__":
    unittest.main()
