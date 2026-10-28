import sys
import time
import unittest
from unittest.mock import patch

from src.processes import CommandError, run_command, terminate


class ProcessTests(unittest.TestCase):
    def test_cleanup_failure_preserves_command_failure_and_closes_pipes(self):
        children = []

        def fail_after_reaping(child):
            terminate(child)
            children.append(child)
            raise OSError("injected cleanup failure")

        with patch("src.processes.terminate", side_effect=fail_after_reaping):
            with self.assertRaisesRegex(CommandError, "status 7") as raised:
                run_command([sys.executable, "-c", "raise SystemExit(7)"])
            self.assertIn("injected cleanup failure", raised.exception.__notes__[0])
            with self.assertRaisesRegex(CommandError, "could not reap") as raised:
                run_command([sys.executable, "-c", "pass"])
            self.assertIsInstance(raised.exception.__cause__, OSError)
        self.assertTrue(all(child.stdout.closed and child.stderr.closed for child in children))
        self.assertTrue(all(child.poll() is not None for child in children))

    def test_real_process_and_separate_streams(self):
        result = run_command(
            [sys.executable, "-c", "import sys; print('hello'); print('err', file=sys.stderr)"]
        )
        self.assertEqual(result.stdout, b"hello\n")
        self.assertEqual(result.stderr, b"err\n")

    def test_failure_is_not_silenced(self):
        command = [sys.executable, "-c", "raise SystemExit(7)"]
        with self.assertRaisesRegex(CommandError, "status 7"):
            run_command(command)
        self.assertEqual(run_command(command, check=False).returncode, 7)

    def test_deadline_and_output_are_bounded(self):
        for code, options in (
            ("import time; time.sleep(60)", {"timeout": 0.1}),
            ("print('x' * 10000)", {"limit": 128}),
            ("import os, time; os.close(1); os.close(2); time.sleep(60)", {"timeout": 0.1}),
        ):
            started = time.monotonic()
            with self.assertRaises(CommandError):
                run_command([sys.executable, "-c", code], **options)
            self.assertLess(time.monotonic() - started, 3)

    def test_missing_executable_and_invalid_arguments(self):
        with self.assertRaises(CommandError) as raised:
            run_command(["/nonexistent-program"])
        self.assertIsInstance(raised.exception.__cause__, OSError)
        for args in ([], ["x\0y"], [None]):
            with self.assertRaises(ValueError):
                run_command(args)


if __name__ == "__main__":
    unittest.main()
