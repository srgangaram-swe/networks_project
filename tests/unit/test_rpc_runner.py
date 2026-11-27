import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src import loopback_campaign, physical_campaign, pipeline, rpc_cli
from src.artifacts import read_json
from src.physical_profile import validate_profile
from src.processes import CommandResult
from src.telemetry import Telemetry
from tests.unit.physical_support import profile, source


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_cli_dispatch_and_retained_cancelled_workload(self):
        args = SimpleNamespace(
            action="client",
            bind="127.0.0.1",
            peer="127.0.0.1",
            port=5300,
            seconds=1,
            output=self.root / "rpc.json",
            allow_isolated=False,
        )
        result = {"status": "cancelled", "admitted_calls": 0}
        with patch.object(rpc_cli, "run_rpc_workload", return_value=result):
            self.assertEqual(rpc_cli._execute(args, Event()), result)
        self.assertEqual(read_json(args.output), result)
        with self.assertRaises(ValueError):
            rpc_cli._execute(args, Event())
        args.output = None
        with self.assertRaises(ValueError):
            rpc_cli._execute(args, Event())
        args.action = "server"
        with patch.object(rpc_cli, "run_server", return_value={"status": "completed"}) as run:
            rpc_cli._execute(args, Event())
            with contextlib.redirect_stdout(io.StringIO()) as out:
                run.call_args.kwargs["ready"](("127.0.0.1", 5300))
            self.assertIn("ready", out.getvalue())
        for answer, expected in (
            ({"status": "completed"}, 0),
            ({"status": "io_error"}, 2),
            (ValueError("bad request"), 2),
        ):
            with (
                patch.object(sys, "argv", ["rpc", "server"]),
                patch.object(
                    rpc_cli,
                    "_execute",
                    side_effect=answer if isinstance(answer, Exception) else None,
                    return_value=answer,
                ),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(rpc_cli.main(), expected)

    def test_remote_controller_profile_cannot_rebind_router_to_client(self):
        value = profile(self.root)
        value["roles"]["client"]["host"] = "remote-client"
        with self.assertRaisesRegex(ValueError, "every role"):
            validate_profile(value)
        for role, item in value["roles"].items():
            item["host"] = "experiment-" + role
        self.assertEqual(validate_profile(value), value)

    def test_preflight_rejects_dirty_source_before_device_changes(self):
        value = profile(self.root)
        with patch.object(
            physical_campaign, "source_identity", return_value={**source(), "dirty": True}
        ):
            with self.assertRaisesRegex(ValueError, "controller"):
                physical_campaign.preflight(value)
        with (
            patch.object(physical_campaign, "source_identity", return_value=source()),
            patch.object(
                physical_campaign,
                "run_command",
                return_value=CommandResult(0, b'{"dirty": true}', b""),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "uncommitted"):
                physical_campaign.preflight(value)

    def test_loopback_plan_and_pipeline_select_real_collection(self):
        plan = pipeline.plan("loopback", transport="tcp", rpc_diagnostics=True)
        self.assertEqual(len(plan["cells"]), 4)
        self.assertEqual({cell["configuration"]["flows"] for cell in plan["cells"]}, {0, 1})
        for kwargs in ({"diagnostic_matrix": True}, {"shadow_forecast": True}):
            with self.assertRaises(ValueError):
                pipeline.plan("loopback", **kwargs)
        with patch.object(loopback_campaign, "collect_loopback") as collect:
            result = pipeline.run(self.root / "pipeline", "loopback", rpc_diagnostics=True)
        self.assertEqual(result["state"], "completed")
        self.assertTrue(collect.call_args.args[1]["rpc_diagnostics"])

    def test_loopback_ledger_stops_on_failure_and_exports_only_complete_runs(self):
        plan = loopback_campaign.loopback_plan(rpc_diagnostics=True)
        for rpc in (False, True):
            target = self.root / str(rpc)
            target.mkdir()
            plan["rpc_diagnostics"] = rpc
            fake = SimpleNamespace(analyze_loopback=Mock(), analyze_rpc=Mock())
            with (
                patch.object(loopback_campaign, "run_trial"),
                patch.object(loopback_campaign, "digest", return_value="a" * 64),
                patch.object(loopback_campaign, "export_diagnostics") as export,
                patch.dict(sys.modules, {"analysis.diagnostic_report": fake}),
            ):
                loopback_campaign.collect_loopback(target, plan, Event(), Telemetry(target))
            self.assertEqual(len(export.call_args.args[0]), 4)
            self.assertEqual(fake.analyze_rpc.call_count, int(rpc))
            self.assertTrue(
                all(
                    item["state"] == "completed"
                    for item in read_json(target / "collection/progress.json")["attempts"]
                )
            )
        stop = Event()
        stop.set()
        target = self.root / "cancel"
        target.mkdir()
        with self.assertRaises(InterruptedError):
            loopback_campaign.collect_loopback(target, plan, stop, Telemetry(target))
