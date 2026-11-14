import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from src import pipeline, pipeline_cli
from src.artifacts import read_json
from src.telemetry import Telemetry
from tests.unit.physical_support import profile, source


class TelemetryTests(unittest.TestCase):
    def test_stages_record_durations_failures_and_bounded_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trace = Telemetry(root)
            with trace.stage("success"):
                pass
            self.assertEqual(read_json(root / "timings.json")["stages"][0]["state"], "completed")
            self.assertGreaterEqual(trace.stages[0]["wall_seconds"], 0)
            error = OSError("measurement failed")
            with self.assertRaises(OSError) as caught:
                with trace.stage("failure"):
                    raise error
            self.assertIs(caught.exception, error)
            self.assertEqual(trace.stages[-1]["error_type"], "OSError")
            trace.events = 4096
            with self.assertRaisesRegex(ValueError, "budget"):
                trace.event("extra")
            trace = Telemetry(None)
            with patch.object(trace, "save", side_effect=OSError("disk full")):
                with self.assertRaises(OSError) as caught:
                    with trace.stage("failed-write"):
                        raise error
            self.assertIs(caught.exception, error)
            self.assertIn("disk full", error.__notes__[-1])
            with patch.object(trace, "save", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    with trace.stage("success-write-failed"):
                        pass
            Telemetry(None).save()


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = {"kind": "local_simulation", "source": source()}

    def test_plan_switches_modes_and_rejects_ambiguous_profiles(self):
        local = pipeline.plan("local")
        self.assertEqual(len(local["schedule"]["cells"]), 48)
        self.assertEqual(local["measurement_slots"], 240000)
        self.assertEqual(pipeline.plan("namespace")["trials"], 16)
        physical = pipeline.plan("physical", profile=profile(self.root))
        self.assertEqual(physical["kind"], "physical_testbed_diagnostics")
        self.assertEqual(len(physical["schedule"]["cells"]), 16)
        self.assertEqual(
            len(
                pipeline.plan("physical", profile=profile(self.root), diagnostic_matrix=True)[
                    "schedule"
                ]["cells"]
            ),
            280,
        )
        for args in (("local", 3, 561, None, True), ("unknown",), ("physical",)):
            with self.assertRaises(ValueError):
                pipeline.plan(*args)

    def test_automatic_stage_order_and_status_keep_analysis_after_successful_export(self):
        stages = []
        trial = {"process_cpu_seconds": 0.1}
        fake_analysis = SimpleNamespace(analyze=lambda *a, **k: stages.append("analysis"))
        for topology in ("local", "physical"):
            with (
                patch.object(pipeline, "plan", return_value=self.plan.copy()),
                patch.object(pipeline, "preflight", return_value={"client": source()}),
                patch.object(
                    pipeline,
                    "collect_simulation",
                    side_effect=lambda *a: stages.append("collect") or [trial],
                ),
                patch.object(
                    pipeline,
                    "collect_physical",
                    side_effect=lambda *a: stages.append("collect") or [trial],
                ),
                patch.object(
                    pipeline, "export_run_tables", side_effect=lambda *a: stages.append("export")
                ),
                patch.dict(sys.modules, {"analysis.policy_comparison": fake_analysis}),
            ):
                result = pipeline.run(
                    self.root / topology, topology, profile=profile(self.root), authorized=True
                )
            self.assertEqual(result["state"], "completed")
            self.assertEqual(stages[-3:], ["collect", "export", "analysis"])
            self.assertEqual(read_json(self.root / topology / "status.json")["state"], "completed")
        with patch("scripts.nucbox_experiment.run") as run:
            pipeline.run(self.root / "namespace", "namespace", authorized=True)
        self.assertIsNotNone(run.call_args.kwargs["telemetry"])

    def test_failure_and_cancellation_retain_cause_without_continuing(self):
        cancel = Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            pipeline.run(self.root / "cancelled", "local", cancel=cancel)
        self.assertFalse((self.root / "cancelled").exists())
        with self.assertRaises(PermissionError):
            pipeline.run(self.root / "denied", "namespace")
        error = OSError("collector failure")
        with patch.object(pipeline, "_execute", side_effect=error):
            with self.assertRaises(OSError) as caught:
                pipeline.run(self.root / "failed", "local")
        self.assertIs(caught.exception, error)
        self.assertEqual(read_json(self.root / "failed/status.json")["state"], "failed")
        with (
            patch.object(pipeline, "_execute", side_effect=error),
            patch("src.pipeline.Telemetry.event", side_effect=OSError("journal full")),
        ):
            with self.assertRaises(OSError) as caught:
                pipeline.run(self.root / "failed-twice", "local")
        self.assertIn("journal full", caught.exception.__notes__[-1])
        cancel.clear()
        with patch.object(pipeline, "_execute", side_effect=lambda *a: cancel.set()):
            with self.assertRaises(InterruptedError):
                pipeline.run(self.root / "late-cancel", "local", cancel=cancel)
        self.assertEqual(read_json(self.root / "late-cancel/status.json")["state"], "cancelled")

    def test_cli_plans_errors_signals_and_namespace_privilege_boundary(self):
        for arguments, expected in (
            (["--topology", "local", "--plan"], 0),
            (["--topology", "local"], 2),
        ):
            with (
                patch.object(sys, "argv", ["pipeline", *arguments]),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(pipeline_cli.main(), expected)
        options = SimpleNamespace(topology="namespace", authorized_isolated_host=True)
        with patch("src.pipeline_cli.platform.system", return_value="Darwin"):
            with self.assertRaises(PermissionError):
                pipeline_cli._namespace_privilege(options)
        with (
            patch("src.pipeline_cli.platform.system", return_value="Linux"),
            patch("src.pipeline_cli.os.geteuid", return_value=1000),
            patch("src.pipeline_cli.os.execvp", side_effect=OSError("sudo unavailable")) as execute,
        ):
            with self.assertRaises(OSError):
                pipeline_cli._namespace_privilege(options)
        self.assertEqual(execute.call_args.args[0], "sudo")
        with (
            patch.object(
                sys, "argv", ["pipeline", "--topology", "local", "--output", str(self.root / "cli")]
            ),
            patch.object(pipeline_cli, "run", side_effect=InterruptedError("stop")),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(pipeline_cli.main(), 130)
