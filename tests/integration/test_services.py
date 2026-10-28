import sys
import time
import unittest
from threading import Event, Timer
from unittest.mock import patch

from src.processes import CommandError, CommandResult, run_command
from src.services import Service


class ServiceTests(unittest.TestCase):
    def test_cleanup_preserves_the_original_error(self):
        service = Service((sys.executable,), b"READY")
        original = OSError("collection failed")
        with patch.object(service, "close", side_effect=CommandError("shutdown failed")):
            service.__exit__(OSError, original, None)
            self.assertIn("shutdown failed", original.__notes__[0])
            with self.assertRaisesRegex(CommandError, "shutdown failed"):
                service.__exit__(None, None, None)

    def test_already_failed_service_is_reported_at_shutdown(self):
        service = Service((sys.executable,), b"READY")
        service.result.set_result(CommandResult(4, b"", b""))
        with patch.object(service.thread, "join"):
            with self.assertRaisesRegex(CommandError, "unsuccessfully"):
                service.close()
        with self.assertRaisesRegex(CommandError, "unexpectedly"):
            service.check_running()

    def test_readiness_across_output_chunks_and_bounded_shutdown(self):
        code = "import time; print('REA',end='',flush=True); print('DY',flush=True); time.sleep(60)"
        with Service((sys.executable, "-u", "-c", code), b"READY") as service:
            service.check_running()
        self.assertFalse(service.thread.is_alive())

    def test_failed_start_and_missing_readiness(self):
        for code in ("raise SystemExit(4)", "import time; time.sleep(60)"):
            with self.assertRaises(CommandError):
                with Service((sys.executable, "-c", code), b"READY", timeout=0.1):
                    self.fail("failed service reported readiness")

    def test_cancellation_after_closed_pipes_does_not_wait_for_full_timeout(self):
        stop = Event()
        timer = Timer(0.1, stop.set)
        timer.start()
        started = time.monotonic()
        try:
            result = run_command(
                (sys.executable, "-c", "import os,time; os.close(1); os.close(2); time.sleep(60)"),
                timeout=20,
                check=False,
                stop=stop,
            )
        finally:
            timer.join(timeout=1)
        self.assertLess(time.monotonic() - started, 3)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
