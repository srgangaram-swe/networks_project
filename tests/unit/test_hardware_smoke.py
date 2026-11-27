import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from src.artifacts import read_json
from src.hardware_smoke import run_smoke, smoke_plan


class HardwareSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "smoke"

    def test_plan_is_portable_and_does_not_run_traffic(self):
        with patch("src.hardware_smoke.run_trial") as trial:
            plan = smoke_plan()
            self.assertEqual((plan["flows"], plan["aggregate_bps"]), (0, 0))
            self.assertFalse(plan["physical_nic_test"])
            self.assertFalse(plan["eligible_for_primary"])
            self.assertEqual(len(plan["policies"]), 4)
            trial.assert_not_called()

    def test_authority_and_platform_checks_precede_output_creation(self):
        with patch("src.hardware_smoke.require_linux") as linux:
            with self.assertRaises(PermissionError):
                run_smoke(self.output, False, Event())
            linux.assert_not_called()
        with patch("src.hardware_smoke.require_linux", side_effect=PermissionError("Linux")):
            with self.assertRaises(PermissionError):
                run_smoke(self.output, True, Event())
        self.assertFalse(self.output.exists())

    def test_success_validates_every_policy_and_never_overwrites(self):
        with (
            patch("src.hardware_smoke.require_linux"),
            patch("src.hardware_smoke.run_trial") as trial,
            patch(
                "src.hardware_smoke.validate_bundle", return_value={"integrity_valid": True}
            ) as validate,
        ):
            report = run_smoke(self.output, True, Event())
            self.assertEqual(report["state"], "completed")
            self.assertEqual(trial.call_count, 4)
            self.assertEqual(validate.call_count, 4)
            for call in trial.call_args_list:
                self.assertEqual((call.args[1].mode, call.args[1].flows), ("namespace", 0))
            before = (self.output / "summary.json").read_bytes()
            with self.assertRaises(FileExistsError):
                run_smoke(self.output, True, Event())
            self.assertEqual((self.output / "summary.json").read_bytes(), before)

    def test_failure_and_validation_error_stop_without_retry(self):
        for target in ("run_trial", "validate_bundle"):
            output = self.output.with_name(target)
            with (
                patch("src.hardware_smoke.require_linux"),
                patch("src.hardware_smoke.run_trial") as trial,
                patch("src.hardware_smoke.validate_bundle") as validate,
            ):
                (trial if target == "run_trial" else validate).side_effect = ValueError("rejected")
                with self.assertRaisesRegex(ValueError, "rejected"):
                    run_smoke(output, True, Event())
                self.assertEqual(trial.call_count, 1)
                self.assertEqual(read_json(output / "summary.json")["state"], "failed")

    def test_cancellation_before_or_between_trials(self):
        cancel = Event()
        cancel.set()
        with patch("src.hardware_smoke.require_linux"):
            with self.assertRaises(InterruptedError):
                run_smoke(self.output, True, cancel)
        self.assertFalse(self.output.exists())
        cancel.clear()
        with (
            patch("src.hardware_smoke.require_linux"),
            patch("src.hardware_smoke.run_trial", side_effect=lambda *a: cancel.set()) as trial,
            patch("src.hardware_smoke.validate_bundle", return_value={"integrity_valid": True}),
        ):
            with self.assertRaises(InterruptedError):
                run_smoke(self.output, True, cancel)
            self.assertEqual(trial.call_count, 1)
            self.assertEqual(read_json(self.output / "summary.json")["state"], "cancelled")

    def test_persistence_failure_does_not_hide_original_error(self):
        from src.artifacts import atomic_json

        def persist(path, value):
            if value.get("state") == "failed":
                raise OSError("disk full")
            atomic_json(path, value)

        with (
            patch("src.hardware_smoke.require_linux"),
            patch("src.hardware_smoke.run_trial", side_effect=RuntimeError("original")),
            patch("src.hardware_smoke.atomic_json", side_effect=persist),
        ):
            with self.assertRaisesRegex(RuntimeError, "original") as raised:
                run_smoke(self.output, True, Event())
            self.assertIn("disk full", raised.exception.__notes__[0])
