import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from analysis.policy_comparison import analyze
from src.artifacts import digest, read_json

ROOT = Path(__file__).resolve().parents[2]


class LocalPipelineTests(unittest.TestCase):
    def test_shell_pipeline_reaches_checked_models_plots_and_findings(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pipeline"
            result = subprocess.run(
                [
                    "sh",
                    str(ROOT / "scripts/run_pipeline.sh"),
                    "--topology",
                    "local",
                    "--workers",
                    "2",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=90,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("stage_started", result.stderr)
            report = read_json(output / "analysis/report.json")
            self.assertEqual(report["runs"], 48)
            self.assertEqual(report["measurement_kind"], "simulation")
            self.assertEqual(report["regression"]["status"], "exploratory_fit")
            self.assertEqual(len(report["plot_layout"]), 12)
            for name, checksum in report["artifacts"].items():
                self.assertEqual(digest(output / "analysis" / name), checksum)
            self.assertIn("SIMULATED DATA", (output / "analysis/insights.txt").read_text())
            self.assertIn(
                "SIMULATED DATA", (output / "analysis/diagnostic_summary.txt").read_text()
            )
            self.assertIn(
                "SIMULATED DATA", (output / "analysis/plots/run_clusters_dbscan.svg").read_text()
            )
            timings = read_json(output / "timings.json")
            self.assertEqual(
                [r["stage"] for r in timings["stages"]], ["simulation", "export", "analysis"]
            )
            with self.assertRaises(ValueError):
                analyze([output / "export"], Path(temporary) / "unlabelled", plots=False)
            replay = analyze(
                [output / "export"],
                Path(temporary) / "replay",
                resamples=100,
                plots=False,
                allow_simulated=True,
            )
            self.assertEqual(replay["runs"], 48)
            events = [
                json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()
            ]
            self.assertEqual(events[-1]["event"], "pipeline_completed")
