import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from src.artifacts import read_json
from src.bundle_validation import validate_bundle
from src.trial import TrialConfig, _phase, run_trial

ROOT = Path(__file__).resolve().parents[2]


def unused_port(kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(
    shutil.which("iperf3"), "iperf3 is required for trial integration; see issue #8"
)
class TrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "run"
        self.config = TrialConfig(
            measurement_seconds=1,
            foreground_port=unused_port(socket.SOCK_DGRAM),
            bulk_port=unused_port(),
        )

    def test_real_trial_validates_and_refuses_overwrite(self):
        result = run_trial(self.path, self.config)
        self.assertEqual(result["state"], "completed")
        summary = validate_bundle(self.path)
        self.assertEqual(summary["measurement_requests"], 500)
        self.assertFalse(summary["eligible_for_primary"])
        with self.assertRaises(FileExistsError):
            run_trial(self.path, self.config)
        self.assertFalse(
            any(thread.name == "experiment-service" for thread in threading.enumerate())
        )
        command = [sys.executable, str(ROOT / "scripts/validate_bundle.py"), str(self.path)]
        cli = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertTrue(json.loads(cli.stdout)["integrity_valid"])
        (self.path / "bulk.json").write_text("{")
        cli = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(cli.returncode, 2)
        self.assertIn("Invalid bundle", cli.stderr)

    def test_cancellation_retains_partial_evidence_and_joins_children(self):
        cancel = Event()

        def interrupt(bundle, state, deadline, event, futures):
            if state == "measurement":
                event.set()
            return _phase(bundle, state, deadline, event, futures)

        with patch("src.trial._phase", side_effect=interrupt):
            with self.assertRaises(InterruptedError):
                run_trial(self.path, self.config, cancel)
        manifest = read_json(self.path / "manifest.json")
        self.assertEqual(manifest["state"], "cancelled")
        self.assertTrue((self.path / "foreground.json").exists())
        self.assertFalse(
            any(thread.name == "experiment-service" for thread in threading.enumerate())
        )
        with self.assertRaises(ValueError):
            validate_bundle(self.path)

    def test_setup_failure_is_not_a_successful_empty_run(self):
        with patch("src.trial.Backend.setup", side_effect=OSError("injected setup failure")):
            with self.assertRaises(OSError):
                run_trial(self.path, self.config)
        manifest = read_json(self.path / "manifest.json")
        self.assertEqual(manifest["state"], "failed")
        self.assertEqual(manifest["errors"][0]["message"], "injected setup failure")

    def test_cleanup_failure_does_not_replace_the_setup_error(self):
        original = OSError("injected setup failure")
        with (
            patch("src.trial.Backend.setup", side_effect=original),
            patch("src.trial.Backend.close", side_effect=RuntimeError("cleanup failed")),
        ):
            with self.assertRaises(OSError) as caught:
                run_trial(self.path, self.config)
        self.assertIs(caught.exception, original)
        self.assertIn("cleanup failed", original.__notes__[0])
        manifest = read_json(self.path / "manifest.json")
        self.assertEqual(manifest["state"], "failed")
        self.assertEqual(manifest["errors"][0]["message"], "injected setup failure")
        self.assertEqual(manifest["errors"][1]["type"], "cleanup_error")


if __name__ == "__main__":
    unittest.main()
