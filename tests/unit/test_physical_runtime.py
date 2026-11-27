import contextlib
import io
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src import physical_campaign, physical_trial, physical_worker
from src.artifacts import atomic_json, read_json
from src.physical_backend import PhysicalBackend
from src.physical_jobs import process_start, register_job, stop_jobs
from src.physical_profile import payload
from src.processes import CommandResult
from src.trial import TrialConfig
from tests.unit.physical_support import profile, source


class PhysicalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".local").mkdir()
        self.profile = profile(self.root)

    def command(self, command, **kwargs):
        if "identity" in command:
            return CommandResult(0, json.dumps(source()).encode(), b"")
        request = json.loads(command[-1])
        if "inspect" in command:
            return CommandResult(
                0,
                json.dumps(
                    {
                        "interfaces": [
                            {"ifindex": {"client": 1, "router": 2, "server": 3}[request["role"]]}
                        ],
                        "network_host": "host",
                    }
                ).encode(),
                b"",
            )
        data = []
        if request["role"] == "router" and "qdisc" in request.get("args", []):
            data = [
                {"dev": "to-client", "kind": "htb", "handle": "1:"},
                {"dev": "to-client", "kind": "bfifo", "parent": "1:10"},
            ]
        return CommandResult(0, json.dumps(data).encode(), b"")

    def test_backend_prepares_checks_commands_and_cleans_every_role(self):
        backend = PhysicalBackend(self.profile, "a" * 12, "fifo")
        with self.assertRaises(RuntimeError):
            backend.command("client", ("true",))
        with patch("src.physical_backend.run_command", side_effect=self.command) as run:
            backend.setup()
            args = backend.command("server", (sys.executable, "/some/foreground.py", "responder"))
            request = json.loads(args[-1])
            self.assertEqual(request["args"][0], str(self.root / ".venv/bin/python"))
            self.assertEqual(backend.snapshot()["kind"], "physical_testbed")
            backend.close()
            backend.close()
        self.assertTrue(run.called)
        backend.prepared = ["client", "router", "server"]
        with patch("src.physical_backend.run_command", side_effect=OSError("offline")) as failed:
            with self.assertRaisesRegex(RuntimeError, "cleanup incomplete"):
                backend.close()
        self.assertEqual(failed.call_count, 3)

    def test_physical_preflight_source_binding_and_plan_limits(self):
        with (
            patch("src.physical_campaign.source_identity", return_value=source()),
            patch("src.physical_campaign.run_command", side_effect=self.command),
        ):
            result = physical_campaign.preflight(self.profile)
        self.assertEqual(set(result), {"client", "router", "server"})
        with (
            patch(
                "src.physical_campaign.source_identity",
                return_value={**source(), "commit": "3" * 40},
            ),
            patch("src.physical_campaign.run_command", side_effect=self.command),
        ):
            with self.assertRaisesRegex(ValueError, "source differs"):
                physical_campaign.preflight(self.profile)
        from src.artifacts import read_json
        from tests.unit.physical_support import ROOT

        raw = read_json(ROOT / "configs/primary.json")
        raw["measurement_seconds"] = 61
        with self.assertRaises(ValueError):
            physical_campaign.physical_plan(raw, source())

    def test_worker_whitelists_privileged_commands_and_keeps_failures(self):
        item = self.profile["roles"]["client"]
        request = {
            "role": "client",
            "token": "a" * 12,
            "item": item,
            "args": ["ip", "-j", "route", "show"],
        }
        lease = MagicMock()
        lease.execute.return_value = CommandResult(7, b"", b"")
        record = {"state": "running"}
        path = self.root / "job.json"
        with (
            patch("src.physical_worker.PhysicalLease.load", return_value=lease),
            patch("src.physical_worker.register_job", return_value=(path, record)),
        ):
            self.assertEqual(physical_worker.execute(request, Event()), 7)
            self.assertEqual(read_json(path)["returncode"], 7)
            request["args"] = [
                str(self.root / ".venv/bin/python"),
                str(self.root / "scripts/foreground.py"),
                "client",
            ]
            physical_worker.execute(request, Event())
            self.assertEqual(lease.execute.call_args.args[0][0], "runuser")
            for bad in ([], "bad", ["x\0y"], ["rm", "anything"]):
                request["args"] = bad
                with self.assertRaises((ValueError, PermissionError)):
                    physical_worker.execute(request, Event())
            request["args"] = ["ip", "-j", "route", "show"]
            lease.execute.side_effect = OSError("workload failed")
            with patch("src.physical_worker.atomic_json", side_effect=OSError("disk failed")):
                with self.assertRaises(OSError) as caught:
                    physical_worker.execute(request, Event())
            self.assertIn("disk failed", caught.exception.__notes__[-1])
        for stream in ("stdout", "stderr"):
            with patch(f"src.physical_worker.sys.{stream}") as output:
                physical_worker._forward(stream, b"data")
            output.buffer.write.assert_called_once_with(b"data")

    def test_worker_actions_and_cli_return_failure_without_changing_handlers(self):
        request = {"role": "client", "token": "a" * 12, "item": self.profile["roles"]["client"]}
        lease = MagicMock(state={"phase": "closed"})
        with (
            patch("src.physical_worker.require_linux"),
            patch("src.physical_worker.inspect_interfaces", return_value=[]),
            patch("src.physical_worker.read_bytes", return_value=b"test boot"),
            patch("src.physical_worker.os.stat", return_value=SimpleNamespace(st_ino=10)),
            patch("src.physical_worker.PhysicalLease.prepare", return_value=lease),
            patch("src.physical_worker.PhysicalLease.load", return_value=lease),
            patch("src.physical_worker.stop_jobs"),
            patch("src.physical_worker.execute", return_value=9),
        ):
            self.assertEqual(
                physical_worker.action("inspect", request, Event())["platform"], "Linux"
            )
            self.assertEqual(
                physical_worker.action("prepare", request, Event()), {"phase": "closed"}
            )
            physical_worker.action("cleanup", request, Event())
            self.assertEqual(physical_worker.action("exec", request, Event()), 9)
            with self.assertRaises(ValueError):
                physical_worker.action("inspect", {**request, "role": "unknown"}, Event())
        for action, result, status in (("inspect", {}, 0), ("exec", 7, 7)):
            with (
                patch.object(sys, "argv", ["worker", action, "--request", payload(request)]),
                patch.object(physical_worker, "action", return_value=result),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(physical_worker.main(), status)
        with (
            patch.object(sys, "argv", ["worker", "inspect", "--request", "[]"]),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(physical_worker.main(), 2)

    def test_trial_identity_fetch_and_mode_checks_do_not_read_arbitrary_files(self):
        with (
            patch.object(physical_trial, "ROOT", self.root),
            patch.object(physical_trial, "source_identity", return_value=source()),
        ):
            self.assertEqual(
                physical_trial.act(
                    "identity", {"role": "client", "item": self.profile["roles"]["client"]}, Event()
                ),
                source(),
            )
            wrong = {**self.profile["roles"]["client"], "repository": "/wrong"}
            with self.assertRaises(ValueError):
                physical_trial.act("identity", {"role": "client", "item": wrong}, Event())
            request = {
                "profile": self.profile,
                "token": "a" * 12,
                "configuration": asdict(
                    TrialConfig(mode="physical", policy="fifo", flows=0, aggregate_bps=0)
                ),
            }
            with patch.object(
                physical_trial, "run_trial", return_value={"state": "completed"}
            ) as run:
                physical_trial.act("run", request, Event())
                self.assertIsInstance(run.call_args.kwargs["backend"], PhysicalBackend)
            destination = self.root / ".local/physical-runs" / ("a" * 12)
            destination.mkdir()
            (destination / "manifest.json").write_text("{}")
            self.assertEqual(
                physical_trial.act("fetch", {**request, "artifact": "manifest.json"}, Event()),
                b"{}",
            )
            with self.assertRaises(ValueError):
                physical_trial.act("fetch", {**request, "artifact": "../../outside"}, Event())
            request["configuration"] = asdict(TrialConfig())
            with self.assertRaises(ValueError):
                physical_trial.act("run", request, Event())
        for result in ({"source": source()}, b"{}"):
            with (
                patch.object(sys, "argv", ["trial", "identity", "--request", "{}"]),
                patch.object(physical_trial, "act", return_value=result),
                patch.object(physical_trial.sys, "stdout"),
            ):
                self.assertEqual(physical_trial.main(), 0)
        with (
            patch.object(sys, "argv", ["trial", "identity", "--request", "[]"]),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(physical_trial.main(), 2)

    def test_worker_registry_holds_start_identity_and_refuses_closed_leases(self):
        directory = self.root / "lease"
        directory.mkdir(mode=0o700)
        atomic_json(directory / "lease.json", {"phase": "active"})
        lease = SimpleNamespace(directory=directory, state={"phase": "active"}, save=lambda: None)
        with patch("src.physical_jobs.process_start", return_value="100"):
            path, record = register_job(lease)
        self.assertEqual(read_json(path)["state"], "running")
        record["pid"] = 12345
        atomic_json(path, record)
        with (
            patch("src.physical_jobs.process_start", side_effect=["100", None]),
            patch("src.physical_jobs._signal_owned") as kill,
        ):
            stop_jobs(lease)
        kill.assert_called_once()
        atomic_json(directory / "lease.json", {"phase": "closed"})
        with self.assertRaises(PermissionError):
            register_job(lease)
        with (
            patch("src.physical_jobs.process_start", return_value="100"),
            patch("src.physical_jobs._signal_owned"),
            patch("src.physical_jobs.time.monotonic", side_effect=[0, 0, 100]),
        ):
            with self.assertRaises(TimeoutError):
                stop_jobs(lease)
        with patch(
            "src.physical_jobs.read_bytes",
            return_value=b"123 (name) " + b"S " + b"0 " * 18 + b"456\n",
        ):
            self.assertEqual(process_start(123), "456")
        with patch("src.physical_jobs.read_bytes", side_effect=FileNotFoundError):
            self.assertIsNone(process_start(123))
        for pid in (True, 1, -1):
            with self.assertRaises(PermissionError):
                process_start(pid)
