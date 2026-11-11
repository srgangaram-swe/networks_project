import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from scripts.setup_environment import _runner
from src.processes import CommandResult

ROOT = Path(__file__).resolve().parents[2]


class EnvironmentCliTests(unittest.TestCase):
    def test_shell_plan_from_another_directory_is_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "new-env"
            result = subprocess.run(
                ["sh", str(ROOT / "scripts/setup_environment.sh"), "--plan", "--venv", str(target)],
                cwd=temporary,
                env={**os.environ, "PYTHON": sys.executable},
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertFalse(plan["system_packages_modified"])
            self.assertEqual(len(plan["requirements"]), 2)
            self.assertFalse(target.exists())

    def test_existing_non_environment_fails_before_package_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "ordinary"
            target.mkdir()
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/setup_environment.py"), "--venv", str(target)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Environment setup failed", result.stderr)
            self.assertEqual(list(target.iterdir()), [])

    def test_cancellation_checks_both_sides_of_the_owned_command(self):
        cancel = Event()
        run = _runner(cancel)
        cancel.set()
        with patch("scripts.setup_environment.run_command") as command:
            with self.assertRaises(InterruptedError):
                run(["unused"])
            command.assert_not_called()
        cancel.clear()

        def finish(*args, **kwargs):
            cancel.set()
            return CommandResult(0, b"", b"")

        with patch("scripts.setup_environment.run_command", side_effect=finish):
            with self.assertRaises(InterruptedError):
                run(["unused"])
