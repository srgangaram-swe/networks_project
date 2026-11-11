import copy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.check_container_result import check
from src.artifacts import atomic_json, read_json

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "data/reference/namespace-pilot-2026-11-11/analysis"


class ContainerResultTests(unittest.TestCase):
    def test_real_reference_and_cli_are_checked_without_traffic(self):
        check(REFERENCE)
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_container_result.py"), str(REFERENCE)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("matches", result.stdout)

    def test_corrupt_reports_and_artifacts_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "analysis"
            shutil.copytree(REFERENCE, target)
            original = read_json(target / "report.json")
            for alter in (
                lambda r: r.update(state="failed"),
                lambda r: r.update(runs=15),
                lambda r: r.update(eligible_for_primary=True),
                lambda r: r.update(eligible_for_primary=0),
                lambda r: r.update(runs=16.0),
                lambda r: r["comparisons"].pop(),
                lambda r: r["comparisons"][0].update(blocks=3),
                lambda r: r["comparisons"][0].update(interval_status="sufficient"),
                lambda r: r["comparisons"][0].update(goodput_mbps=1000000),
                lambda r: r.update(artifacts=[]),
                lambda r: r["artifacts"].pop("run_clusters.png"),
                lambda r: r["artifacts"].update({"../outside": "0" * 64}),
            ):
                changed = copy.deepcopy(original)
                alter(changed)
                atomic_json(target / "report.json", changed)
                with self.assertRaises(ValueError):
                    check(target)
            atomic_json(target / "report.json", original)
            (target / "runs.csv").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                check(target)
