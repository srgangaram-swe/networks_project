import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from scripts import nucbox_experiment
from src.artifacts import read_json
from tests.analysis.support import ROOT


class EntrypointTests(unittest.TestCase):
    def test_portable_plan_and_authorization_failure(self):
        planned = nucbox_experiment.plan()
        self.assertEqual(planned["trials"], 16)
        self.assertIn("tsne", planned["analysis"])
        self.assertFalse(planned["eligible_for_primary"])
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "not-created"
            with self.assertRaises(PermissionError):
                nucbox_experiment.run(destination, False, Event())
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/nucbox_experiment.py"),
                    "run",
                    "--output",
                    str(destination),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse(destination.exists())

    def test_ordered_stages_and_retained_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "run"
            events = []
            with (
                patch.object(nucbox_experiment, "require_linux"),
                patch.object(nucbox_experiment, "local_hardware", return_value={}),
                patch.object(
                    nucbox_experiment, "run_smoke", side_effect=lambda *_: events.append("smoke")
                ),
                patch.object(
                    nucbox_experiment,
                    "create_campaign",
                    side_effect=lambda *_: events.append("create"),
                ),
                patch.object(
                    nucbox_experiment,
                    "execute_campaign",
                    side_effect=lambda *a, **kw: events.append("campaign"),
                ),
                patch(
                    "scripts.export_pilot.export", side_effect=lambda *_: events.append("export")
                ),
                patch(
                    "analysis.policy_comparison.analyze",
                    side_effect=lambda *_: events.append("analysis"),
                ),
            ):
                result = nucbox_experiment.run(destination, True, Event())
            self.assertEqual(events, ["smoke", "create", "campaign", "export", "analysis"])
            self.assertEqual(result["state"], "completed")
            destination = Path(temporary) / "failed"
            with (
                patch.object(nucbox_experiment, "require_linux"),
                patch.object(
                    nucbox_experiment, "local_hardware", side_effect=OSError("read failed")
                ),
            ):
                with self.assertRaises(OSError):
                    nucbox_experiment.run(destination, True, Event())
            self.assertEqual(read_json(destination / "status.json")["stage"], "inspection")
            self.assertEqual(read_json(destination / "status.json")["state"], "failed")
