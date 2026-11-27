import json
import tempfile
import unittest
from pathlib import Path

from src.environment import environment_plan, setup_environment
from src.processes import CommandError, CommandResult


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "venv"
        self.commands = []
        self.identity = None
        self.install_result = CommandResult(0, b"", b"")

    def fake_run(self, args, **options):
        self.commands.append((args, options))
        if args[1:3] == ["-m", "venv"]:
            self.path.mkdir()
            (self.path / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
        if args[1:2] == ["-c"]:
            value = self.identity or [str(self.path), str(self.path.parent), [3, 12, 0]]
            return CommandResult(0, json.dumps(value).encode(), b"")
        if "install" in args:
            return self.install_result
        return CommandResult(0, b"", b"")

    def test_creation_reuse_profile_and_deadlines(self):
        result = setup_environment(self.path, run=self.fake_run)
        self.assertTrue(result["created"])
        self.assertEqual([options["timeout"] for _, options in self.commands], [60, 10, 300, 30])
        self.assertEqual(self.commands[2][0].count("-r"), 2)
        self.commands.clear()
        result = setup_environment(self.path, "analysis", run=self.fake_run)
        self.assertFalse(result["created"])
        self.assertEqual(self.commands[1][0].count("-r"), 1)
        self.assertEqual(len(self.commands), 3)

    def test_invalid_paths_and_profiles_never_launch_commands(self):
        with self.assertRaises(ValueError):
            environment_plan(self.path, "unknown")
        self.path.write_text("ordinary user file")
        with self.assertRaises(ValueError):
            setup_environment(self.path, run=self.fake_run)
        self.path.unlink()
        self.path.symlink_to(self.path.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            setup_environment(self.path, run=self.fake_run)
        with self.assertRaises(ValueError):
            environment_plan(self.path.parent / "missing" / "env", "analysis")
        self.assertEqual(self.commands, [])

    def test_existing_non_environment_or_shared_packages_are_rejected(self):
        self.path.mkdir()
        with self.assertRaises(FileNotFoundError):
            setup_environment(self.path, run=self.fake_run)
        (self.path / "pyvenv.cfg").write_text("include-system-site-packages = true\n")
        with self.assertRaisesRegex(ValueError, "exclude system"):
            setup_environment(self.path, run=self.fake_run)
        self.assertEqual(self.commands, [])

    def test_interpreter_identity_is_checked_before_install(self):
        self.path.mkdir()
        (self.path / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
        for identity in (
            [str(self.path.parent), str(self.path.parent), [3, 12, 0]],
            [str(self.path), str(self.path), [3, 12, 0]],
            [str(self.path), str(self.path.parent), [3, 9, 0]],
            [str(self.path), str(self.path.parent), [3, 12]],
            [str(self.path), str(self.path.parent), [True, 12, 0]],
            [str(self.path), str(self.path.parent), "3.12"],
            [None, "base", [3, 12, 0]],
            [str(self.path), None, [3, 12, 0]],
            {"unexpected": "identity"},
            ["short"],
        ):
            self.identity = identity
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                setup_environment(self.path, run=self.fake_run)
        self.assertTrue(all("install" not in args for args, _ in self.commands))

    def test_install_failure_keeps_partial_environment_and_bounded_detail(self):
        self.install_result = CommandResult(7, b"", b"missing wheel")
        with self.assertRaisesRegex(RuntimeError, "exited 7: missing wheel"):
            setup_environment(self.path, run=self.fake_run)
        self.assertTrue((self.path / "pyvenv.cfg").exists())

        def timeout(*args, **kwargs):
            raise CommandError("deadline")

        with self.assertRaisesRegex(CommandError, "deadline"):
            setup_environment(self.path, run=timeout)
