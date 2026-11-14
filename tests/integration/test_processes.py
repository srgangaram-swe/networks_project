import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import MagicMock, call, patch

from src.processes import CommandError, _signal_group, run_command, terminate


class ProcessTests(unittest.TestCase):
    def test_darwin_zombie_group_requires_reaped_child_and_disappeared_group(self):
        child = MagicMock(pid=12345)
        denied = PermissionError("group excludes exited processes")
        with (
            patch("src.processes.sys.platform", "darwin"),
            patch("src.processes.os.killpg", side_effect=[denied, ProcessLookupError]) as send,
        ):
            _signal_group(child, signal.SIGTERM)
        child.wait.assert_called_once_with(timeout=0.1)
        self.assertEqual(send.call_args_list, [call(12345, signal.SIGTERM), call(12345, 0)])

    def test_live_or_unverified_permission_failure_remains_an_error(self):
        for platform, wait_error, signals in (
            ("linux", None, [PermissionError("denied")]),
            ("darwin", subprocess.TimeoutExpired("owned", 0.1), [PermissionError("denied")]),
            ("darwin", None, [PermissionError("denied"), None]),
            ("darwin", None, [PermissionError("denied"), PermissionError("still denied")]),
        ):
            child = MagicMock(pid=12345)
            child.wait.side_effect = wait_error
            with (
                patch("src.processes.sys.platform", platform),
                patch("src.processes.os.killpg", side_effect=signals),
            ):
                with self.assertRaises(PermissionError):
                    _signal_group(child, signal.SIGTERM)

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
        diagnostic = [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('reason:' + 'x'*2000); sys.exit(8)",
        ]
        with self.assertRaisesRegex(CommandError, "reason:") as caught:
            run_command(diagnostic)
        self.assertLess(len(str(caught.exception)), 1200)

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
