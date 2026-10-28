import subprocess
import unittest
from unittest.mock import Mock, patch

from src.testbed_inventory import TOOLS, inspect_tools, local_inventory


class InventoryTests(unittest.TestCase):
    def test_local_wrapper_uses_detected_platform(self):
        with patch("src.testbed_inventory.platform.system", return_value="Darwin"):
            self.assertEqual(local_inventory()["platform"], "Darwin")

    def test_unsupported_platform_never_executes_commands(self):
        find, run = Mock(), Mock()
        report = inspect_tools("Darwin", find, run)
        self.assertEqual(report["status"], "unsupported_platform")
        self.assertEqual(report["checks"], [])
        self.assertFalse(report["ready_for_experiment"])
        find.assert_not_called()
        run.assert_not_called()

    def test_missing_tools_never_execute(self):
        run = Mock()
        report = inspect_tools("Linux", Mock(return_value=None), run)
        self.assertTrue(all(check["status"] == "missing" for check in report["checks"]))
        self.assertEqual(len(report["checks"]), len(TOOLS))
        run.assert_not_called()

    def test_success_does_not_certify_support_or_publish_paths(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 0))
        report = inspect_tools("Linux", lambda name: "/private/tools/" + name, run)
        self.assertTrue(all(check["status"] == "available" for check in report["checks"]))
        self.assertFalse(report["ready_for_experiment"])
        self.assertFalse(report["network_changes"])
        self.assertNotIn("/private", str(report))
        for call, (tool, flag) in zip(run.call_args_list, TOOLS, strict=True):
            self.assertEqual(call.args[0], ["/private/tools/" + tool, flag])
            self.assertEqual(call.kwargs["timeout"], 5)
            self.assertEqual(call.kwargs["stdout"], subprocess.DEVNULL)
            self.assertNotIn("shell", call.kwargs)

    def test_failures_are_distinct_and_never_promoted_to_success(self):
        for failure, status in (
            (subprocess.CompletedProcess([], 1), "command_failed"),
            (subprocess.TimeoutExpired("tc", 5), "timeout"),
            (OSError("not executable"), "unavailable"),
        ):
            run = (
                Mock(side_effect=failure)
                if isinstance(failure, Exception)
                else Mock(return_value=failure)
            )
            report = inspect_tools("Linux", lambda name: name, run)
            self.assertTrue(all(check["status"] == status for check in report["checks"]))
            self.assertFalse(report["ready_for_experiment"])
